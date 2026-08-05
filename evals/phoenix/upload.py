"""Push the goldens to a running Phoenix as one dataset per task.

    uv run python -m evals.phoenix.upload

Reads the endpoint from ``PHOENIX_COLLECTOR_ENDPOINT`` (default the local
``phoenix serve``). Re-running versions the same named datasets. This talks to the
server; it is not part of the default test run.
"""

from __future__ import annotations

import sys

from evals.phoenix.client import endpoint, make_client
from evals.phoenix.dataset import DATASETS, examples_for_task


def main() -> int:
    client = make_client()
    print(f"uploading {len(DATASETS)} datasets to {endpoint()}")
    for name, task in DATASETS.items():
        examples = examples_for_task(task)
        dataset = client.datasets.create_dataset(name=name, examples=examples)
        dataset_id = getattr(dataset, "id", dataset)
        print(f"  {name:18} {len(examples):3d} examples  -> {dataset_id}")
    print(f"\nview them at {endpoint()}/datasets")
    return 0


if __name__ == "__main__":
    sys.exit(main())
