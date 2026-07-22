"""ENG-6a — bulk-ingest a public dataset CSV for training data backfill.

Usage:
    python scripts/training/ingest_public_dataset.py \\
        --source bdg2 \\
        --file tests/fixtures/datasets/bdg2_sample.csv \\
        --tenant-id <uuid> --building-id <uuid>

Requires APP_DATABASE_URL pointed at a migrated database (0009+) and a
tenant/building already onboarded (see services/tenant_admin or the
Tenant/Admin API's POST /v1/tenant/buildings) -- this script populates
normalized_readings for an existing building, it does not create tenants.

Does not trigger live analysis (see pipelines/dataset_ingestion/ingest.py's
NullEventPublisher docstring for why) or run feature engineering --
run scripts/training/backfill_features.py afterward to populate the
feature store from the readings this ingests.
"""

from __future__ import annotations

import argparse
import asyncio
from uuid import UUID

from pipelines.dataset_ingestion.ingest import ingest_public_dataset


async def _run(args: argparse.Namespace) -> None:
    summary = await ingest_public_dataset(
        file_path=args.file,
        source_id=args.source,
        tenant_id=args.tenant_id,
        building_id=args.building_id,
        chunk_size=args.chunk_size,
    )
    print(  # noqa: T201
        f"Ingested {summary.file_path} (source={summary.source_id}): "
        f"{summary.chunks_processed} chunks, {summary.total_rows} raw rows -> "
        f"pass={summary.pass_count} degraded={summary.degraded_count} "
        f"quarantined={summary.quarantined_count} "
        f"({len(summary.batch_ids)} ingestion_batches records)"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Bulk-ingest a public dataset CSV")
    parser.add_argument("--source", required=True, choices=["combed", "bdg2"])
    parser.add_argument("--file", required=True, help="Path to the dataset CSV")
    parser.add_argument("--tenant-id", type=UUID, required=True)
    parser.add_argument("--building-id", type=UUID, required=True)
    parser.add_argument("--chunk-size", type=int, default=5000)
    args = parser.parse_args()

    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
