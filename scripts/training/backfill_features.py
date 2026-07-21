"""ENG-6b — backfill the feature store from already-ingested readings.

Run after scripts/training/ingest_public_dataset.py (or against a
building that's simply accumulated real normalized_readings over time)
to populate feature_store in one pass, rather than waiting for
AnalysisPipelineWorkflow runs to accumulate feature history circuit-window
by circuit-window.

Usage:
    python scripts/training/backfill_features.py \\
        --tenant-id <uuid> --building-id <uuid> \\
        --window-days 90
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
from uuid import UUID

from pipelines.feature_engineering.batch_pipeline import run_batch_feature_engineering


async def _run(args: argparse.Namespace) -> None:
    window_end = datetime.datetime.now(datetime.UTC)
    window_start = window_end - datetime.timedelta(days=args.window_days)

    features = await run_batch_feature_engineering(
        tenant_id=args.tenant_id,
        building_id=args.building_id,
        window_start=window_start,
        window_end=window_end,
    )
    print(  # noqa: T201
        f"Backfilled {len(features)} feature_store rows for building={args.building_id} "
        f"(window={args.window_days}d)"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill the feature store from readings")
    parser.add_argument("--tenant-id", type=UUID, required=True)
    parser.add_argument("--building-id", type=UUID, required=True)
    parser.add_argument("--window-days", type=int, default=90)
    args = parser.parse_args()

    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
