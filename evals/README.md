# chess-coach evaluations

A standalone framework that grades the chess coach against objective ground
truth. It is **not** part of the shipped `chess_coach` package and does **not**
run in the default `pytest` (which is scoped to `tests/`). Run it explicitly with
`pytest evals/`.

## Philosophy

- **Exact-match first.** Structured answers — the move, the assessment bucket, the
  endgame result — are graded by exact comparison against Stockfish/book ground
  truth (the text-to-SQL approach: grade the answer, not the prose). An LLM judges
  only coaching quality that code cannot grade: explanations, mistake diagnosis
  and multi-turn teaching, and only when asked.
- **Deterministic and offline by default.** The default run uses local Stockfish
  and no network. The `judge` marker gates the only network-dependent tests.
- **A reference solver proves the framework.** The suite is run against a
  Stockfish-backed `OracleTask` and goes green — validating the harness, metrics
  and data. The real coach is a separate, pending target (see below).

## Layout

| Path | What |
|------|------|
| `harness/` | The `CoachTask` boundary, the pinned Stockfish oracle, pure checkers, and the reference/stub tasks. |
| `data/` | The golden schema + loader, committed `goldens/*.json`, and curated candidate banks. |
| `metrics/` | Deterministic exact-match metrics + the opt-in explanation judge. |
| `tools/` | Offline scripts: vision extraction, golden validation, score report. |
| `tests/` | Unit tests + the dataset-driven eval for each task type. |

## Setup

```sh
brew install stockfish poppler        # engine ground truth; PDF page rendering
uv sync --extra evals                 # deepeval, anthropic, pdf2image, pillow
```

The oracle finds Stockfish via `$STOCKFISH_PATH` or `stockfish` on the `PATH`.

## Running

```sh
uv run pytest evals/ -m "not judge"           # deterministic suite (green baseline)
COACH_TASK=agent uv run pytest evals/ -m "not judge"   # real-agent target (xfail until built)
uv run pytest evals/ -m judge                 # LLM-as-judge (needs ANTHROPIC_API_KEY)
uv run python -m evals.tools.validate_goldens # re-prove every golden vs Stockfish
uv run python -m evals.tools.report           # per-task pass rates → results/latest.json
```

`COACH_TASK` selects the system under test: `oracle` (default) or `agent`. Wire
the real coach in by making it satisfy `evals.harness.task.CoachTask` and
selecting it here.

## Phoenix experiments (optional)

A thin layer in `evals/phoenix/` mirrors the goldens into [Arize Phoenix](
https://phoenix.arize.com/) as versioned **datasets** and runs the coach as a Phoenix
**experiment**, graded by evaluators that reuse the exact metrics above. It sits
*alongside* the pytest gate — the deterministic suite stays the source of truth; Phoenix
adds dataset versioning, per-example scores, and run-to-run comparison in a UI.

```sh
uv sync --extra evals                          # installs arize-phoenix-client
phoenix serve                                  # local UI + collector at :6006
uv run python -m evals.phoenix.upload          # goldens -> one dataset per task
uv run python -m evals.phoenix.run --limit 3   # smoke the oracle (dry run) on a subset

# grade the real agent, with its tool spans nested under each experiment run:
COACH_TASK=agent CHESS_COACH_TRACING_ENABLED=1 uv run python -m evals.phoenix.run
```

Datasets (one per task): `chess-best-move` (20), `chess-eval-bucket` (20),
`chess-endgame` (20), `chess-deep-line` (20), `chess-teaching` (12),
`chess-mistake-diagnosis` (10), `chess-multi-turn-teaching` (10),
`chess-conversation` (50), `chess-general-chat` (20). The structured datasets grade
by exact match; the explanation/teaching/conversation judges attach only when
`ANTHROPIC_API_KEY` is set. The endpoint is read from `PHOENIX_COLLECTOR_ENDPOINT`
(default `http://localhost:6006`). View datasets and experiments at that URL.

## Task types

- **best_move** (tactics) — the coach's move must equal an accepted solution.
- **eval_bucket** — the coach's assessment (`winning`…`losing`) must match the
  bucket derived from the engine score.
- **endgame** — the coach must play a key move *and* name the result (win/draw/loss).
- **deep_line** — the coach must calculate a short 3-5 ply continuation and explain
  the plan behind both sides' moves.
- **mistake_diagnosis** — the coach must diagnose a student's played/proposed move:
  the missed engine-best move, concrete refutation and reusable weakness.
- **teaching** — a single live teaching turn, with spoiler control when the student
  asks for a hint.
- **multi_turn_teaching** — a scripted hint ladder/conversation: guide first,
  respond to the student's guess, reveal only on the allowed turn, then summarize.
- **conversation** — the coach must answer the next turn in a stored multi-turn
  teacher-student dialogue; deterministic policy checks catch cheap failures, and
  the opt-in judge grades context awareness and teaching quality.
- **general_chat** — the coach answers a non-position chess question in prose,
  judged against source-backed key facts and a paraphrased reference answer.

Every golden also carries a source-backed explanation (`reference_explanation`)
and its `key_ideas`. The opt-in explanation/general-chat judges
(`pytest evals/ -m judge`) grade the coach's prose against those facts, so the
eval covers *understanding* and coaching usefulness, not only engine-checkable
answers.

## The dataset

182 goldens. The core 72 are **36 original positions plus 36 color-mirrored
derivatives** (balanced by side to move), extended by 20 deep-line continuations,
10 mistake-diagnosis and 10 multi-turn teaching examples, 50 teacher-student
conversations, and 20 general-chat prompts:

- **best_move** — 20 total: 10 White-to-move, 10 Black-to-move.
- **eval_bucket** — 20 total: 10 White-to-move, 10 Black-to-move, balanced across
  all five buckets.
- **endgame** — 20 total: 10 White-to-move, 10 Black-to-move.
- **teaching** — 12 total: 6 White-to-move, 6 Black-to-move.
- **deep_line** — 20 total: book-derived multi-move examples, with 4 intermediate,
  12 advanced and 4 expert-level prompts.
- **mistake_diagnosis** — 10 curated student-mistake examples from game-like
  fragments, each with `student_move`, `engine_best_move`, `engine_refutation` and
  `expected_weakness_tags`.
- **multi_turn_teaching** — 10 scripted conversations with per-turn reveal policy
  (`conversation[].reveal_allowed`) and `expected_reveal_turn`.
- **conversation** — 50 total: paraphrased teacher-student dialogues, with 15 short,
  25 medium, and 10 long-context cases.
- **general_chat** — 20 total: 4 beginner, 8 intermediate, 8 advanced.

The single-position deterministic subset is 60 goldens (`best_move`, `eval_bucket`,
`endgame`); the 20 `deep_line` continuations add deterministic grading against the
real agent (the Stockfish oracle xfails them) plus an opt-in explanation judge. The
coaching-quality goldens (`teaching`, `mistake_diagnosis`, `multi_turn_teaching`,
`conversation`, `general_chat`) are judged only in the opt-in `judge` run (the
`conversation` goldens also get lightweight deterministic policy checks). Every
position is verified with Stockfish/python-chess where it has an engine-checkable
anchor (the move is the engine's or an accepted equivalent, the bucket is the
engine's, the endgame result is not refuted) and every one carries reference
explanation text as ground truth.

Sourcing:

- **endgame** — theoretical positions from *Silman's Complete Endgame Course*
  (Lucena and Philidor transcribed from the book diagrams; basic mates, opposition,
  square rule, wrong-bishop and opposite-bishop draws, plus the Réti study).
- **best_move** — exact positions illustrating the mating and tactical motifs of
  *Yusupov, Build Up Your Chess 1* (back-rank, smothered, Arabian and supported
  mates, forks, pins, discovered check, deflection, underpromotion).
- **eval_bucket** — positions illustrating the imbalances of *Silman, The Amateur's
  Mind* (material up/down a piece, rook, pawn; and balanced/equal positions).
- **general_chat** — non-position questions selected from
  `data/candidates/general_chat_top100.json`, mostly backed by the local chess
  book PDFs (`~/Desktop/chess-books-eval`) with Chess Stack Exchange high-vote
  questions used for common student framing. Answers are paraphrased into key
  facts to avoid copying book text.
- **deep_line** — positions and themes derived from the chess-book corpus, extended
  into legal 3-5 ply continuations and checked with python-chess/Stockfish for
  sequence sanity. These are intended for the real agent target; the single-position
  Stockfish oracle xfails them because it does not reproduce book continuations.

Mirrored derivatives are generated by vertically mirroring the board and swapping
piece colors with `python-chess`, mirroring accepted moves to UCI, and preserving
side-to-move-relative expected buckets/results. When Stockfish chooses an
equivalent endgame key move after mirroring, that move is included in the accepted
set.

The scanned books (*Silman*, *Amateur's Mind*) have no text layer, so their diagrams
are read by rendering pages; the few-piece theoretical endgames are transcribed
exactly and Stockfish-confirmed, while the busy tactical/assessment positions are
encoded as clean, engine-verified illustrations of the book's named motif/imbalance
(`extraction.method` records which: `book-diagram`, `canonical`, `motif-illustration`,
`imbalance-illustration`).

## Growing the dataset

To pull further positions straight from book *diagrams*, author a manifest of the
problems you want (`{id, book, page, task, level, theme, expected_result?}`) and run:

```sh
uv run python -m evals.tools.extract_problems --manifest my_manifest.json
```

Each page is rendered and read by Claude vision in one call, then **validated by
python-chess and Stockfish**. Clean extractions land in `data/staged.json` for you
to review and fold into `data/goldens/`; illegal, engine-disagreeing or
low-confidence ones are quarantined in `results/quarantine.json`. Nothing is added
to the committed dataset without human review.

Goldens are pinned to the engine that authored them; after regenerating data or
upgrading Stockfish, run `validate_goldens` to catch drift.
