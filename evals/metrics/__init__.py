"""Grading metrics: deterministic first, LLM-as-judge only when asked.

The three deterministic metrics compare the coach's *structured* answer against
Stockfish/book ground truth by exact match — the text-to-SQL philosophy of
grading the answer, not the prose:

- :class:`~evals.metrics.best_move.BestMoveMetric`
- :class:`~evals.metrics.deep_line.DeepLineMetric`
- :class:`~evals.metrics.eval_bucket.EvalBucketMetric`
- :class:`~evals.metrics.endgame.EndgameTechniqueMetric`

The explanation, mistake-diagnosis and multi-turn teaching judges are imported
lazily by the opt-in ``judge`` tests so the default run stays network-free.
"""

from evals.metrics.best_move import BestMoveMetric
from evals.metrics.conversation import ConversationPolicyMetric
from evals.metrics.deep_line import DeepLineMetric
from evals.metrics.endgame import EndgameTechniqueMetric
from evals.metrics.eval_bucket import EvalBucketMetric

__all__ = [
    "BestMoveMetric",
    "ConversationPolicyMetric",
    "DeepLineMetric",
    "EndgameTechniqueMetric",
    "EvalBucketMetric",
]
