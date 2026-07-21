"""ENG-6c/6e — CLI wrapper around pipelines.training.train_and_evaluate().

Usage:
    python scripts/training/run_training.py \\
        --tenant-id <uuid> --building-id <uuid> \\
        --building-type office --trigger calendar
"""

from __future__ import annotations

import argparse
import asyncio
from uuid import UUID

from pipelines.training.report import format_training_summary
from pipelines.training.train_and_evaluate import train_and_evaluate


async def _run(args: argparse.Namespace) -> None:
    summary = await train_and_evaluate(
        tenant_id=args.tenant_id,
        building_id=args.building_id,
        building_type=args.building_type,
        trigger=args.trigger,
        window_days=args.window_days,
    )
    print(format_training_summary(summary))  # noqa: T201


def main() -> None:
    parser = argparse.ArgumentParser(description="Train and evaluate the ML Ensemble")
    parser.add_argument("--tenant-id", type=UUID, required=True)
    parser.add_argument("--building-id", type=UUID, required=True)
    parser.add_argument("--building-type", default="unknown")
    parser.add_argument(
        "--trigger", default="calendar", choices=["calendar", "drift", "feedback_volume"]
    )
    parser.add_argument("--window-days", type=int, default=90)
    args = parser.parse_args()

    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
