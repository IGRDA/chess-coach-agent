"""The deterministic grader behind the move-evaluation eval.

The whole eval rests on reading a prose reply as a verdict, so the reader itself
needs tests: a grader that quietly mislabels replies would move the score without
the coach changing at all. Network-free — no coach is run here.
"""

from __future__ import annotations

import pytest

from evals.tools.run_move_eval import Outcome, classify, names_move, summarize


# -- classify -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "reply",
    [
        "That's a blunder — Nxd5 just loses a piece to the recapture.",
        "It's a mistake here; the engine prefers Re1.",
        "Not the best. It's too slow and lets Black consolidate.",
        "I'd avoid that: it drops a pawn for nothing.",
        "Careful — that move gets refuted by ...Qa5+.",
    ],
)
def test_a_reply_that_condemns_the_move_reads_as_bad(reply: str) -> None:
    assert classify(reply) == "bad"


@pytest.mark.parametrize(
    "reply",
    [
        "Good move! That's the engine's top choice.",
        "Nothing wrong with that — it's perfectly playable.",
        "Yes, that's solid and keeps your structure intact.",
        "That is a strong move and well spotted.",
    ],
)
def test_a_reply_that_endorses_the_move_reads_as_sound(reply: str) -> None:
    assert classify(reply) == "sound"


def test_a_mixed_reply_follows_the_side_it_commits_to() -> None:
    """Coaches soften bad news; the verdict is where the weight falls, not the tone."""
    reply = (
        "It's a natural move and I see why it's tempting, but it drops a pawn "
        "and it's a mistake here — the engine wants Re1 instead."
    )
    assert classify(reply) == "bad"


@pytest.mark.parametrize(
    "reply",
    [
        "Let's think about what the position is asking for.",
        "What does that move do about the pressure on your back rank?",
        "",
    ],
)
def test_a_reply_with_no_verdict_is_unclear_not_guessed(reply: str) -> None:
    """A hedge is a failed answer; scoring it would flatter the coach."""
    assert classify(reply) == "unclear"


def test_a_balanced_reply_is_unclear_rather_than_coin_flipped() -> None:
    assert classify("It is a good move but it is also a mistake.") == "unclear"


# -- attribution: the verdict must be about the *student's* move --------------------


def test_praise_for_the_recommended_alternative_is_not_praise_for_the_move() -> None:
    """The regression that invalidated the first baseline.

    A correct answer to a bad move condemns it and then recommends a better one, so
    the reply is full of approving language — aimed at a different move. Scoring the
    whole reply read this as endorsement and marked a correct coach wrong.
    """
    reply = (
        "**Bxf7+ is actually a blunder** — you end up simply down a bishop. "
        "What should you look for instead? The engine suggests **d4** as the best "
        "move. Other solid moves like d3 and O-O are also good and keep your edge."
    )
    assert classify(reply, "Bxf7+") == "bad"


def test_a_sound_move_is_still_endorsed_when_alternatives_are_mentioned() -> None:
    """The mirror case: excluding alternatives must not swallow genuine approval."""
    reply = (
        "Nxe5 is a good move — it wins a clean pawn and the engine likes it. "
        "The best move is arguably d4 instead, but yours is perfectly playable."
    )
    assert classify(reply, "Nxe5") == "sound"


def test_a_reply_that_never_names_the_move_falls_back_to_the_whole_text() -> None:
    """Coaches switch to 'it' after the first mention; that must still grade."""
    assert classify("Honestly, it's a mistake and it drops a pawn.", "Nxe5") == "bad"


def test_markdown_emphasis_around_the_move_does_not_hide_it() -> None:
    assert classify("**Nxd5** is a blunder here.", "Nxd5") == "bad"


# -- minimised losses are endorsements, not condemnations ---------------------------


@pytest.mark.parametrize(
    "reply",
    [
        "Yes, exd5 is a good move! It only gives up a tiny amount versus the best.",
        "dxc4 is a sound move — it loses only a tiny bit compared to the very best.",
        "Nf3 is perfectly playable; it concedes a shade against the top choice.",
    ],
)
def test_quantifying_a_small_cost_does_not_condemn_the_move(reply: str) -> None:
    """The regression that failed two plainly-approving replies.

    A coach saying "this costs almost nothing" is endorsing the move; scoring the
    bare verb as a negative cancelled the praise and produced "unclear".
    """
    assert classify(reply) == "sound"


def test_a_real_loss_is_still_condemned() -> None:
    """The minimiser must not become a blanket excuse for the word 'loses'."""
    assert classify("Nxe5 loses a piece to the recapture.") == "bad"
    assert classify("That drops a whole rook.") == "bad"


# -- summarize ----------------------------------------------------------------------


def _outcome(
    *, sound: bool, verdict: str, ms: float = 1000.0, named: bool = False
) -> Outcome:
    return Outcome(
        id="x",
        expected_sound=sound,
        verdict=verdict,
        correct=verdict == ("sound" if sound else "bad"),
        cp_loss=0 if sound else 300,
        latency_ms=ms,
        reply_chars=100,
        expected_reply="Kxf7",
        named_reply=named,
    )


# -- names_move: the reason axis ----------------------------------------------------


def test_the_reply_is_recognised_when_the_coach_names_it() -> None:
    assert names_move("After Kxf7 you have no follow-up.", "Kxf7") is True


@pytest.mark.parametrize("written", ["Kxf7", "Kxf7+", "Kxf7!", "**Kxf7**", "...Kxf7"])
def test_notation_variants_of_the_same_move_all_count(written: str) -> None:
    """Coaches decorate moves; the engine does not. The move is what matters."""
    assert names_move(f"Black plays {written} and is a piece up.", "Kxf7+") is True


def test_a_different_move_to_the_same_square_does_not_count() -> None:
    """Nd5 and Nxd5 are different moves; crediting one for the other inflates the score."""
    assert names_move("The knight goes to Nd5.", "Nxd5") is False


def test_a_move_embedded_in_a_longer_token_does_not_count() -> None:
    assert names_move("The d4d5 push", "d4") is False


def test_no_expected_reply_is_never_credited() -> None:
    """Mating moves have no reply; they must not score a free point."""
    assert names_move("Anything at all.", "") is False


# -- the taught score ---------------------------------------------------------------


def test_taught_requires_both_the_verdict_and_the_reason() -> None:
    """The headline number: a right grade with no reason is not teaching."""
    outcomes = [
        _outcome(sound=False, verdict="bad", named=True),  # verdict + reason
        _outcome(sound=False, verdict="bad", named=False),  # verdict only
        _outcome(sound=False, verdict="sound", named=True),  # reason without verdict
        _outcome(sound=False, verdict="unclear", named=False),  # neither
    ]
    summary = summarize(outcomes)

    assert summary["accuracy"] == 0.5  # two right verdicts
    assert summary["named_reply"] == 0.5  # two named the reply
    assert summary["taught"] == 0.25  # only one did both


def test_taught_can_never_exceed_accuracy() -> None:
    """Invariant: teaching is a subset of being right."""
    outcomes = [_outcome(sound=False, verdict="bad", named=n) for n in (True, False)]
    summary = summarize(outcomes)
    assert summary["taught"] <= summary["accuracy"]


def test_summary_splits_accuracy_by_band() -> None:
    """The split is the point: a coach that distrusts everything must be visible."""
    outcomes = [
        _outcome(sound=False, verdict="bad"),
        _outcome(sound=False, verdict="bad"),
        _outcome(sound=True, verdict="bad"),  # wrongly condemned a good move
        _outcome(sound=True, verdict="sound"),
    ]
    summary = summarize(outcomes)

    assert summary["n"] == 4
    assert summary["accuracy"] == 0.75
    assert summary["accuracy_bad"] == 1.0
    assert summary["accuracy_sound"] == 0.5


def test_always_saying_bad_scores_only_the_bad_half() -> None:
    """The dataset's balance is what makes 50% — not 0% — the do-nothing baseline."""
    outcomes = [_outcome(sound=False, verdict="bad") for _ in range(5)]
    outcomes += [_outcome(sound=True, verdict="bad") for _ in range(5)]

    summary = summarize(outcomes)
    assert summary["accuracy"] == 0.5
    assert summary["accuracy_sound"] == 0.0


def test_summary_reports_latency_percentiles_from_the_same_run() -> None:
    outcomes = [_outcome(sound=False, verdict="bad", ms=float(n)) for n in range(1, 11)]
    summary = summarize(outcomes)

    assert summary["latency_p50_ms"] == 5.0
    assert summary["latency_p90_ms"] == 9.0


def test_unclear_replies_are_counted_and_never_scored_correct() -> None:
    outcomes = [_outcome(sound=True, verdict="unclear")]
    summary = summarize(outcomes)

    assert summary["unclear"] == 1
    assert summary["accuracy"] == 0.0


def test_an_empty_run_summarises_without_dividing_by_zero() -> None:
    summary = summarize([])
    assert summary["n"] == 0 and summary["accuracy"] == 0.0
    assert summary["valid"] is False


# -- run integrity: a collapsed run must not read as a result -----------------------


def test_a_run_that_mostly_errored_is_marked_invalid() -> None:
    """The regression that produced a triumphant '100%' from 3 of 18 turns.

    Three surviving turns all happened to be from the same band, so the run scored
    100% while having measured essentially nothing.
    """
    outcomes = [_outcome(sound=False, verdict="bad") for _ in range(3)]
    summary = summarize(outcomes, attempted=18)

    assert summary["accuracy"] == 1.0  # the raw number is still computed…
    assert summary["valid"] is False  # …but it is flagged as not a measurement
    assert summary["coverage"] == pytest.approx(3 / 18)


def test_a_complete_run_is_valid() -> None:
    outcomes = [_outcome(sound=False, verdict="bad") for _ in range(9)]
    outcomes += [_outcome(sound=True, verdict="sound") for _ in range(9)]
    summary = summarize(outcomes, attempted=18)

    assert summary["valid"] is True
    assert summary["coverage"] == 1.0


def test_a_run_missing_a_few_turns_is_still_valid() -> None:
    """Coverage is a threshold, not perfection: one flaky turn must not void a run."""
    outcomes = [_outcome(sound=False, verdict="bad") for _ in range(17)]
    summary = summarize(outcomes, attempted=18)

    assert summary["valid"] is True
