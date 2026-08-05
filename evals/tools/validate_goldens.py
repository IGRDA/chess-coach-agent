"""Re-prove every committed golden against python-chess and Stockfish.

Loading already enforces the schema (legal FEN, legal moves, required ground-truth
field). This tool adds the *engine* check the dataset's correctness rests on: that
each golden still agrees with Stockfish — the tactic's move is the engine's move,
the assessment bucket matches the engine score, the endgame result is not refuted,
and judge-only diagnosis examples name the same engine-best anchor. Run it after
regenerating data or bumping the engine to catch drift; it exits non-zero if
anything disagrees.

    uv run python -m evals.tools.validate_goldens [--depth N]
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from evals.data.loader import load_goldens
from evals.data.schema import ChessGolden
from evals.harness.checkers import normalize_move
from evals.harness.engine import DEFAULT_DEPTH, StockfishOracle


@dataclass(frozen=True)
class Issue:
    golden_id: str
    detail: str


def check_golden(golden: ChessGolden, oracle: StockfishOracle) -> list[Issue]:
    """Return engine-agreement issues for one golden (empty == consistent)."""
    if golden.task in {"teaching", "general_chat", "conversation"}:
        return []
    issues: list[Issue] = []
    if golden.fen is None:
        return issues
    a = oracle.assess(golden.fen)
    accepted = {normalize_move(golden.fen, m) for m in golden.solution_moves}

    if golden.task == "best_move":
        if a.best_move_uci not in accepted:
            issues.append(
                Issue(
                    golden.id,
                    f"engine best {a.best_move_uci} not in {sorted(accepted)}",
                )
            )
    elif golden.task == "eval_bucket":
        if a.bucket != golden.expected_bucket:
            issues.append(
                Issue(
                    golden.id, f"engine bucket {a.bucket} != {golden.expected_bucket}"
                )
            )
    elif golden.task == "endgame":
        if a.best_move_uci not in accepted:
            issues.append(
                Issue(
                    golden.id,
                    f"engine key move {a.best_move_uci} not in {sorted(accepted)}",
                )
            )
        if a.result() != golden.expected_result:
            issues.append(
                Issue(
                    golden.id, f"engine result {a.result()} != {golden.expected_result}"
                )
            )
    elif golden.task in {"mistake_diagnosis", "multi_turn_teaching"}:
        if golden.engine_best_move is not None:
            expected = normalize_move(golden.fen, golden.engine_best_move)
            if a.best_move_uci != expected:
                issues.append(
                    Issue(golden.id, f"engine best {a.best_move_uci} != {expected}")
                )
        elif accepted and a.best_move_uci not in accepted:
            issues.append(
                Issue(
                    golden.id,
                    f"engine best {a.best_move_uci} not in {sorted(accepted)}",
                )
            )
    return issues


def validate(depth: int = DEFAULT_DEPTH) -> tuple[list[ChessGolden], list[Issue]]:
    """Validate every golden; return the goldens and any issues found."""
    goldens = load_goldens()
    issues: list[Issue] = []
    with StockfishOracle(depth=depth) as oracle:
        for golden in goldens:
            issues.extend(check_golden(golden, oracle))
    return goldens, issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--depth", type=int, default=DEFAULT_DEPTH)
    args = parser.parse_args()

    goldens, issues = validate(args.depth)
    for issue in issues:
        print(f"FAIL {issue.golden_id}: {issue.detail}")
    print(
        f"\nchecked {len(goldens)} goldens at depth {args.depth}: "
        f"{len(goldens) - len({i.golden_id for i in issues})} consistent, "
        f"{len({i.golden_id for i in issues})} with issues"
    )
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
