"""Turn a curated selection of book problems into validated goldens (vision).

Books are scanned images, so positions are read from board *diagrams* by a vision
model — but only for the problems a human has hand-picked in a manifest, never a
whole-book sweep. Each page is rendered once and sent to Claude in one
token-economical call that returns a standard FEN plus the solution. Nothing is
trusted on faith: every extraction is put through python-chess (legal FEN/moves)
and Stockfish (the tactic's move is the engine's; the assessment bucket is the
engine's; the endgame result is not refuted). Clean extractions are written to a
staging file for a human to fold into the dataset; anything illegal, engine-
disagreeing or low-confidence is quarantined for review.

    uv run python -m evals.tools.extract_problems --manifest path/to/manifest.json

Manifest = a JSON list of entries: ``{id, book, page, task, level, theme,
expected_result?, dpi?}``. Needs ``ANTHROPIC_API_KEY`` for the real extractor.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from evals.data.schema import ChessGolden, Extraction
from evals.harness.checkers import is_valid_fen, normalize_move
from evals.harness.engine import DEFAULT_DEPTH, StockfishOracle
from evals.harness.task import EndgameResult

VISION_MODEL = "claude-opus-4-8"
MIN_CONFIDENCE = 0.6
STAGING = Path(__file__).resolve().parents[1] / "data" / "staged.json"
QUARANTINE = Path(__file__).resolve().parents[1] / "results" / "quarantine.json"
ExtractableTaskType = Literal["best_move", "eval_bucket", "endgame"]

_PROMPT = (
    "This image is a chess problem from a book. Read the board diagram and reply "
    "with ONLY a compact JSON object, no prose:\n"
    '{"fen": "<standard FEN, include correct side to move>", '
    '"solution": ["<best/key move in SAN>", ...], '
    '"confidence": <0..1>}\n'
    "If side to move is not stated, infer it from the problem (usually the side "
    "to play and win). If you cannot read the position, set confidence to 0."
)


@dataclass(frozen=True)
class ManifestEntry:
    id: str
    book: str
    page: int
    task: ExtractableTaskType
    level: str = "intermediate"
    theme: list[str] = field(default_factory=list)
    expected_result: EndgameResult | None = None
    dpi: int = 150


@dataclass(frozen=True)
class Extracted:
    """The raw, unvalidated reading of one diagram."""

    fen: str
    solution: list[str]
    confidence: float


class Extractor(Protocol):
    def __call__(self, image_png: bytes, entry: ManifestEntry) -> Extracted: ...


def render_page(entry: ManifestEntry) -> bytes:
    """Render the manifest page to PNG bytes (one tight image, modest DPI)."""
    from pdf2image import convert_from_path

    images = convert_from_path(
        entry.book, dpi=entry.dpi, first_page=entry.page, last_page=entry.page
    )
    if not images:
        raise ValueError(f"no page {entry.page} in {entry.book}")
    import io

    buffer = io.BytesIO()
    images[0].save(buffer, format="PNG")
    return buffer.getvalue()


def claude_extractor(image_png: bytes, entry: ManifestEntry) -> Extracted:
    """Read a diagram with Claude vision in a single, terse call."""
    from anthropic import Anthropic

    client = Anthropic()
    message = client.messages.create(
        model=VISION_MODEL,
        max_tokens=300,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": base64.b64encode(image_png).decode(),
                        },
                    },
                    {"type": "text", "text": _PROMPT},
                ],
            }
        ],
    )
    text = "".join(block.text for block in message.content if block.type == "text")
    data = json.loads(text)
    return Extracted(
        fen=data["fen"],
        solution=list(data.get("solution", [])),
        confidence=float(data.get("confidence", 0.0)),
    )


def build_golden(
    entry: ManifestEntry, extracted: Extracted, oracle: StockfishOracle
) -> tuple[ChessGolden | None, list[str]]:
    """Validate an extraction into a golden, or return the reasons it was rejected."""
    reasons: list[str] = []
    if extracted.confidence < MIN_CONFIDENCE:
        reasons.append(f"low confidence {extracted.confidence:.2f}")
    if not is_valid_fen(extracted.fen):
        return None, [*reasons, f"illegal FEN {extracted.fen!r}"]

    try:
        moves = [normalize_move(extracted.fen, m) for m in extracted.solution]
    except ValueError as exc:
        return None, [*reasons, str(exc)]

    assessment = oracle.assess(extracted.fen)
    expected_bucket: str | None = None
    expected_result: EndgameResult | None = None

    if entry.task == "best_move":
        if assessment.best_move_uci not in moves:
            reasons.append(f"engine best {assessment.best_move_uci} not in {moves}")
    elif entry.task == "eval_bucket":
        expected_bucket = assessment.bucket  # engine defines the ground truth
    elif entry.task == "endgame":
        expected_result = entry.expected_result
        if assessment.best_move_uci not in moves:
            reasons.append(f"engine key move {assessment.best_move_uci} not in {moves}")
        if assessment.result() != entry.expected_result:
            reasons.append(
                f"engine result {assessment.result()} != {entry.expected_result}"
            )

    if reasons:
        return None, reasons

    golden = ChessGolden(
        id=entry.id,
        source=f"{Path(entry.book).stem} p.{entry.page}",
        fen=extracted.fen,
        task=entry.task,
        solution_moves=moves if entry.task != "eval_bucket" else [],
        expected_bucket=expected_bucket,
        expected_result=expected_result,
        theme=entry.theme,
        level=entry.level,
        extraction=Extraction(
            method="vision",
            model=VISION_MODEL,
            confidence=extracted.confidence,
            validated_by=["python-chess", "stockfish"],
        ),
    )
    return golden, []


def load_manifest(path: Path) -> list[ManifestEntry]:
    raw = json.loads(path.read_text())
    return [ManifestEntry(**item) for item in raw]


def run(
    manifest_path: Path,
    *,
    extractor: Extractor = claude_extractor,
    depth: int = DEFAULT_DEPTH,
) -> tuple[list[ChessGolden], list[dict[str, object]]]:
    """Extract every manifest problem; return accepted goldens and quarantined ones."""
    entries = load_manifest(manifest_path)
    accepted: list[ChessGolden] = []
    quarantined: list[dict[str, object]] = []
    with StockfishOracle(depth=depth) as oracle:
        for entry in entries:
            try:
                extracted = extractor(render_page(entry), entry)
                golden, reasons = build_golden(entry, extracted, oracle)
            except Exception as exc:  # noqa: BLE001 - record, never crash the batch
                golden, reasons = None, [f"error: {exc}"]
            if golden is not None:
                accepted.append(golden)
            else:
                quarantined.append({"id": entry.id, "reasons": reasons})
    return accepted, quarantined


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--depth", type=int, default=DEFAULT_DEPTH)
    args = parser.parse_args()

    accepted, quarantined = run(args.manifest, depth=args.depth)

    STAGING.parent.mkdir(exist_ok=True)
    STAGING.write_text(
        json.dumps([g.model_dump(exclude_none=True) for g in accepted], indent=2) + "\n"
    )
    if quarantined:
        QUARANTINE.parent.mkdir(exist_ok=True)
        QUARANTINE.write_text(json.dumps(quarantined, indent=2) + "\n")

    print(f"accepted {len(accepted)} → {STAGING} (review, then fold into goldens/)")
    print(
        f"quarantined {len(quarantined)}" + (f" → {QUARANTINE}" if quarantined else "")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
