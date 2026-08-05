"""Phoenix integration for the eval harness: datasets, task, evaluators, runner.

A thin layer *alongside* the deepeval suite (which stays the deterministic gate). It
mirrors the committed goldens into versioned Arize Phoenix **datasets**, runs the same
coach under test as a Phoenix **experiment** (auto-traced), and grades it with
**evaluators that reuse the existing metrics verbatim** — so the Phoenix scoreboard and
the local one can never disagree on grading. Nothing here re-implements grading logic.
"""
