"""Parsing the agent's final message into a structured answer (no network)."""

from __future__ import annotations

import pytest

from chess_coach.adapters.coach.agent import CoachAgentError, _parse_answer


def test_parses_fenced_json_block() -> None:
    text = (
        "Rc8# is mate: the rook checks and the knight covers the escape squares.\n"
        '```json\n{"best_move": "c1c8", "eval_bucket": "winning", '
        '"result": "win", "explanation": "Back-rank mate."}\n```'
    )
    ans = _parse_answer(text)
    assert ans.best_move == "c1c8"
    assert ans.eval_bucket == "winning"
    assert ans.result == "win"
    assert ans.explanation == "Back-rank mate."


def test_takes_the_last_json_block() -> None:
    text = (
        '```json\n{"best_move": "a1a1", "explanation": "draft"}\n```\n'
        "and my final answer:\n"
        '```json\n{"best_move": "e2e4", "explanation": "final"}\n```'
    )
    assert _parse_answer(text).best_move == "e2e4"


def test_null_and_none_fields_become_absent() -> None:
    text = (
        '```json\n{"best_move": "e2e4", "eval_bucket": null, '
        '"result": "none", "explanation": "x"}\n```'
    )
    ans = _parse_answer(text)
    assert ans.best_move == "e2e4"
    assert ans.eval_bucket is None
    assert ans.result is None


def test_parses_deep_line_array() -> None:
    text = (
        '```json\n{"best_move": "e2e4", "line": ["e2e4", "e7e5", "g1f3"], '
        '"explanation": "White takes the center and develops."}\n```'
    )
    ans = _parse_answer(text)
    assert ans.best_move == "e2e4"
    assert ans.line == ["e2e4", "e7e5", "g1f3"]


def test_bare_json_fallback() -> None:
    text = 'Here it is: {"best_move": "d2d4", "explanation": "central control"}'
    assert _parse_answer(text).best_move == "d2d4"


def test_no_json_raises() -> None:
    with pytest.raises(CoachAgentError):
        _parse_answer("I think the position is roughly equal, hard to say.")
