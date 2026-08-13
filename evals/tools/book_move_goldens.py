"""Turn reconstructed book games into graded *move-evaluation* problems.

The question this dataset exists to answer is narrow: when a student proposes a
concrete move, does the coach judge it correctly? Answering it needs positions
where a *tempting* move is also a *bad* one — the case where an ungrounded coach
is most likely to nod along with the student.

Where each half of a problem comes from:

* **The position** comes from the book — real master games (:mod:`book_games`
  reconstructs them from the PDF, and every move is legality-checked, so a FEN
  here is a position that was actually played), not synthetic material.
* **The verdict** comes from Stockfish, which is the arbiter the coach's answer is
  graded against anyway.

Note what is *not* circular here. The engine grades the coach's prose, not the
engine's own tool: the score to beat is whether the coach — asked in natural
language about a concrete move — reaches the same verdict the engine holds. A
coach with no move-evaluation tool must guess it; one with the tool can look.

Candidates are drawn from the forcing moves (captures and checks) because those
are what a student actually asks about, and kept only when the loss lands in a
band that is unambiguously a mistake yet not a one-move catastrophe any beginner
would see.

    uv run python -m evals.tools.book_move_goldens \\
        --book "~/Desktop/chess-books-eval/Chessbook - ... .pdf" --limit 20
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import chess

from chess_coach.adapters.coach.analysis import MemoizingAnalyzer, StockfishAnalyzer
from chess_coach.adapters.coach.tools import evaluate_move, position_features
from evals.tools.book_games import BookGame, games_from_book

# A candidate must give up at least this much to count as a genuine mistake, and
# no more than this much to stay instructive rather than an obvious give-away.
MIN_LOSS_CP = 150
MAX_LOSS_CP = 1200

# The control band. A dataset made only of bad moves is not an evaluation: a coach
# that answers "that's a mistake" every time would score full marks on it. These
# are forcing moves that *look* the same to a student but are actually sound, so
# the score can only be earned by telling the two apart.
CONTROL_MAX_LOSS_CP = 20

# Opening moves are book theory rather than student judgement, so the first few
# plies of each game are skipped.
SKIP_OPENING_PLIES = 8

# Keep the set diverse: no game may dominate it.
MAX_PER_GAME = 3

DEFAULT_OUT = Path(__file__).resolve().parents[1] / "data" / "move_eval" / "book_moves.json"
GENERATION_DEPTH = 16


@dataclass(frozen=True)
class Problem:
    """One position with a tempting move the engine says is a mistake."""

    fen: str
    student_move_san: str
    student_move_uci: str
    best_move_uci: str
    best_move_san: str
    cp_loss: int
    verdict: str
    score_after: str
    game_index: int
    ply: int
    # The consequence of the student's move: the opponent's best answer and the
    # line that follows. This is the *reason* the move is good or bad, as opposed
    # to cp_loss, which only says how it ranks against a different move.
    reply_san: str
    line_san: tuple[str, ...]


def _tempting_moves(fen: str) -> list[str]:
    """The forcing moves a student is most likely to propose: captures and checks."""
    features = position_features(fen)
    seen: list[str] = []
    for move in features.captures + features.checks:
        if move not in seen:
            seen.append(move)
    return seen


def _band(cp_loss: int) -> str | None:
    """Which side of the eval this candidate belongs to, or None if in between."""
    if MIN_LOSS_CP <= cp_loss <= MAX_LOSS_CP:
        return "bad"
    if cp_loss <= CONTROL_MAX_LOSS_CP:
        return "sound"
    return None


def problems_from_game(analyzer: object, game: BookGame) -> dict[str, list[Problem]]:
    """Scan one game for tempting moves that are losing, and ones that are sound."""
    found: dict[str, list[Problem]] = {"bad": [], "sound": []}
    for ply, move in enumerate(game.moves):
        if ply < SKIP_OPENING_PLIES:
            continue
        if len(found["bad"]) + len(found["sound"]) >= MAX_PER_GAME:
            break
        fen = move.fen_before
        if chess.Board(fen).is_check():
            continue  # forced replies teach little about choosing a move
        for candidate in _tempting_moves(fen):
            try:
                evaluation = evaluate_move(analyzer, fen, candidate)  # type: ignore[arg-type]
            except (ValueError, RuntimeError):
                continue
            band = _band(evaluation.cp_loss)
            if band is None:
                continue
            best = analyzer.analyze(fen)  # type: ignore[attr-defined]
            found[band].append(
                Problem(
                    fen=fen,
                    student_move_san=evaluation.move_san,
                    student_move_uci=evaluation.move_uci,
                    best_move_uci=best.best_move_uci,
                    best_move_san=best.best_move_san,
                    cp_loss=evaluation.cp_loss,
                    verdict=evaluation.verdict,
                    score_after=evaluation.score_text,
                    game_index=game.index,
                    ply=ply,
                    reply_san=evaluation.reply_san,
                    line_san=tuple(evaluation.line_san),
                )
            )
            break  # one problem per position keeps the set varied
    return found


def to_golden(problem: Problem, book: str, band: str) -> dict:
    """Render a problem as a ``ChessGolden`` record for the eval harness."""
    is_sound = band == "sound"
    # The refutation is a *line*, not a distance. "Gives up 332 centipawns" grades
    # the move against a different one; "Kxf7 and you have no follow-up" is the
    # answer to what the student actually asked.
    line = " ".join(problem.line_san)
    consequence = (
        f"After {problem.student_move_san}, the opponent's best answer is "
        f"{problem.reply_san}" + (f" and play continues {line}" if line else "")
        if problem.reply_san
        else f"{problem.student_move_san} ends the game immediately"
    )
    if is_sound:
        refutation = (
            f"{consequence}, reaching {problem.score_after} — {problem.cp_loss} "
            f"centipawns off the engine's {problem.best_move_san}, so it is sound."
        )
        ideas = [
            f"{problem.student_move_san} is playable",
            "confirm, do not invent a problem",
        ]
        tags = ["talking a student out of a good move"]
    else:
        refutation = (
            f"{consequence}, reaching {problem.score_after} for the side to move — "
            f"{problem.cp_loss} centipawns worse than {problem.best_move_san}."
        )
        ideas = [
            f"{problem.student_move_san} is a {problem.verdict}",
            f"{problem.reply_san} refutes it" if problem.reply_san else "it ends the game",
            f"{problem.best_move_san} is stronger",
        ]
        tags = ["accepting a tempting move without checking"]
    return {
        "id": f"book-move-{band}-g{problem.game_index}-p{problem.ply}",
        "source": f"{book} (reconstructed game {problem.game_index}, ply {problem.ply})",
        "fen": problem.fen,
        "task": "mistake_diagnosis",
        "solution_moves": [problem.best_move_uci],
        # Identical phrasing for both bands on purpose: the coach must not be able
        # to infer the answer from how the question is asked.
        "student_message": (
            f"I was thinking about playing {problem.student_move_san} here. "
            "Is that a good move?"
        ),
        "student_move": problem.student_move_uci,
        "engine_best_move": problem.best_move_uci,
        "engine_refutation": refutation,
        "expected_weakness_tags": tags,
        "key_ideas": ideas,
        "theme": ["move-evaluation", "mistake-diagnosis", problem.verdict],
        "level": "intermediate",
        "extraction": {
            "method": "book-text-reconstruction+stockfish",
            "validated_by": ["python-chess", "stockfish"],
        },
        # Not part of ChessGolden; kept alongside for the deterministic scorer.
        "_expected_verdict": problem.verdict,
        "_expected_sound": is_sound,
        "_cp_loss": problem.cp_loss,
        # The reason axis: a coach that has understood the move can name the reply
        # that answers it, and that is checkable without a judge.
        "_expected_reply": problem.reply_san,
        "_expected_line": list(problem.line_san),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--book", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--depth", type=int, default=GENERATION_DEPTH)
    # The bands define what the dataset is *for*: the default is obvious blunders,
    # while a narrow low band ("--min-loss 60 --max-loss 140") makes the subtle
    # inaccuracy set that separates a grounded coach from a guessing one.
    parser.add_argument("--min-loss", type=int, default=MIN_LOSS_CP)
    parser.add_argument("--max-loss", type=int, default=MAX_LOSS_CP)
    parser.add_argument("--control-max-loss", type=int, default=CONTROL_MAX_LOSS_CP)
    parser.add_argument("--skip-plies", type=int, default=SKIP_OPENING_PLIES)
    parser.add_argument("--per-game", type=int, default=MAX_PER_GAME)
    args = parser.parse_args(argv)

    globals().update(
        MIN_LOSS_CP=args.min_loss,
        MAX_LOSS_CP=args.max_loss,
        CONTROL_MAX_LOSS_CP=args.control_max_loss,
        SKIP_OPENING_PLIES=args.skip_plies,
        MAX_PER_GAME=args.per_game,
    )

    book_path = args.book.expanduser()
    if not book_path.exists():
        print(f"book not found: {book_path}", file=sys.stderr)
        return 2

    games = [g for g in games_from_book(book_path) if g.plies > SKIP_OPENING_PLIES]
    print(f"reconstructed {len(games)} usable games", file=sys.stderr)

    bands: dict[str, list[Problem]] = {"bad": [], "sound": []}
    with StockfishAnalyzer(depth=args.depth) as engine:
        analyzer = MemoizingAnalyzer(engine)
        for game in games:
            if sum(len(v) for v in bands.values()) >= args.limit * 2:
                break
            found = problems_from_game(analyzer, game)
            for band, items in found.items():
                bands[band].extend(items)
            print(
                f"  game {game.index}: {game.plies} plies -> "
                f"{len(found['bad'])} bad, {len(found['sound'])} sound",
                file=sys.stderr,
            )

    # Balance the two bands so the score cannot be won by always answering the
    # same way; the smaller band sets the size.
    per_band = min(args.limit // 2, min(len(bands["bad"]), len(bands["sound"])))
    goldens = [
        to_golden(p, book_path.stem, band)
        for band in ("bad", "sound")
        for p in bands[band][:per_band]
    ]
    print(
        f"balanced to {per_band} per band "
        f"(available: {len(bands['bad'])} bad, {len(bands['sound'])} sound)",
        file=sys.stderr,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(goldens, indent=2) + "\n")
    print(f"wrote {len(goldens)} goldens to {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
