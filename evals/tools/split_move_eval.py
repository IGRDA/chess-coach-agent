"""Split the move-evaluation pool into a dev set and a held-out set.

Prompt tuning is a search, and a search run against the same problems it is scored
on will find the problems rather than the weakness. The dev set is what iteration
is allowed to see; the held-out set is opened once, at the end, to say whether the
gain was real.

The split is by *source game*, not by problem. Two positions from the same game
share an opening, a pawn structure and often the very tactic that decides them, so
splitting at the problem level would leak the answer across the boundary while
looking properly separated. Both halves are kept band-balanced, so the "always say
mistake" floor stays at 50% on each.

    uv run --extra evals python -m evals.tools.split_move_eval --pool pool.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "move_eval"
_GAME = re.compile(r"-g(\d+)-p\d+$")


def game_of(golden: dict[str, Any]) -> int:
    """The index of the reconstructed game a problem came from."""
    found = _GAME.search(golden["id"])
    if not found:
        raise ValueError(f"cannot read a game index from id {golden['id']!r}")
    return int(found.group(1))


def split(
    pool: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Deal whole games alternately into two band-balanced halves.

    Games are dealt largest-first so the two halves end up similar in size, and each
    game goes to whichever half currently holds fewer problems of the bands it
    carries — which keeps sound/bad balanced without ever splitting a game.
    """
    by_game: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for golden in pool:
        by_game[game_of(golden)].append(golden)

    halves: tuple[list[dict[str, Any]], list[dict[str, Any]]] = ([], [])
    for _, problems in sorted(by_game.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        target = 0 if len(halves[0]) <= len(halves[1]) else 1
        halves[target].extend(problems)
    return halves


def rebalance(goldens: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Trim to an equal number of sound and bad problems."""
    sound = [g for g in goldens if g["_expected_sound"]]
    bad = [g for g in goldens if not g["_expected_sound"]]
    keep = min(len(sound), len(bad))
    return sound[:keep] + bad[:keep]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool", type=Path, default=DATA_DIR / "pool.json")
    parser.add_argument("--dev", type=Path, default=DATA_DIR / "dev.json")
    parser.add_argument("--holdout", type=Path, default=DATA_DIR / "holdout.json")
    args = parser.parse_args(argv)

    pool = json.loads(args.pool.read_text())
    first, second = split(pool)
    dev, holdout = rebalance(first), rebalance(second)

    shared = {game_of(g) for g in dev} & {game_of(g) for g in holdout}
    if shared:
        print(f"games leaked across the split: {shared}", file=sys.stderr)
        return 1

    args.dev.write_text(json.dumps(dev, indent=2) + "\n")
    args.holdout.write_text(json.dumps(holdout, indent=2) + "\n")
    for name, part in (("dev", dev), ("holdout", holdout)):
        sound = sum(1 for g in part if g["_expected_sound"])
        print(
            f"{name:8} n={len(part):3}  sound={sound}  bad={len(part) - sound}  "
            f"games={sorted({game_of(g) for g in part})}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
