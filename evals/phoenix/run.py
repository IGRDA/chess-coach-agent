"""Run the coach against the Phoenix datasets as experiments, and grade it.

    uv run python -m evals.phoenix.run                    # all four datasets
    uv run python -m evals.phoenix.run --task chess-endgame
    uv run python -m evals.phoenix.run --limit 3          # smoke a subset (dry run)

Selects the system under test with ``COACH_TASK`` (``oracle`` default, ``agent``,
``pending``) exactly like the pytest suite, and reuses the same metrics as evaluators.
For a real agent run, set ``COACH_TASK=agent``; tracing defaults on so the coach's tool
spans nest under each experiment. Requires the datasets to have been uploaded first
(``python -m evals.phoenix.upload``) and a running Phoenix.
"""

from __future__ import annotations

import argparse
import os
import sys

from chess_coach.adapters.observability import tracing
from chess_coach.composition.config import Settings
from evals.phoenix.client import endpoint, make_client
from evals.phoenix.dataset import DATASETS
from evals.phoenix.evaluators import evaluators_for
from evals.phoenix.task import COACH_TASK_ENV, coach_task_context


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", choices=sorted(DATASETS), help="one dataset only")
    parser.add_argument(
        "--dry-run", action="store_true", help="run without persisting the experiment"
    )
    parser.add_argument(
        "--limit", type=int, default=0, help="smoke only the first N examples (dry run)"
    )
    args = parser.parse_args()

    from phoenix.client.experiments import run_experiment

    coach = os.environ.get(COACH_TASK_ENV, "oracle")
    settings = Settings()
    traced = tracing.configure_tracing(
        enabled=settings.tracing_enabled,
        otlp_endpoint=settings.otlp_endpoint,
        native_telemetry=settings.native_telemetry,
        native_otlp_endpoint=settings.native_otlp_endpoint,
    )
    names = [args.task] if args.task else list(DATASETS)
    # A positive --limit runs N examples in dry-run mode (the client's int dry_run).
    dry_run: bool | int = args.limit if args.limit else args.dry_run

    client = make_client()
    print(f"running coach={coach} against {endpoint()} ({len(names)} dataset(s))")
    with coach_task_context() as task:
        for name in names:
            task_type = DATASETS[name]
            dataset = client.datasets.get_dataset(dataset=name)
            run_experiment(
                dataset=dataset,
                task=task,
                evaluators=evaluators_for(task_type),
                experiment_name=f"{coach}-{task_type}",
                dry_run=dry_run,
                client=client,
            )
    if traced:
        from opentelemetry import trace

        provider = trace.get_tracer_provider()
        if hasattr(provider, "shutdown"):
            provider.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
