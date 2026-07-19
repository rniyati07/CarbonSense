"""ENG-5b — the Ingestion API's write-path orchestration, extracted out of
apps/api/routers/ingestion.py so the router stays a thin HTTP wrapper with
no business logic (the "No ML/business logic in apps/api" constraint):
resolving a raw row's meter_id/circuit_type, auto-provisioning circuits,
running DataQualityGate, persisting readings, and publishing the resulting
event are all ingestion-domain concerns, not API-layer concerns.

Both the CSV upload endpoint and the smart-meter push receiver call this
single function -- one code path through DataQualityGate, not two.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from orchestration.events.kafka.producer import EventPublisher
from services.ingestion.config import DataQualityGateConfig
from services.ingestion.event_publisher import DataQualityEventPublisher
from services.ingestion.models import RawIngestionBatch
from services.ingestion.normalization import resolve_columns
from services.ingestion.quality_gate import DataQualityGate
from services.ingestion.repository import IngestionWriteRepository


async def ingest_raw_rows(
    session: AsyncSession,
    tenant_id: UUID,
    building_id: UUID,
    raw_rows: list[dict[str, Any]],
    ingestion_source: str,
    event_publisher: EventPublisher,
) -> UUID:
    config = DataQualityGateConfig()
    mapped_rows, _ = resolve_columns(raw_rows, config.get_source("default").column_mapping)

    meter_types: dict[str, str] = {}
    for row in mapped_rows:
        meter_id = str(row.get("circuit_id") or "").strip()
        if not meter_id:
            continue
        meter_types.setdefault(meter_id, str(row.get("circuit_type") or "main_feed"))

    write_repo = IngestionWriteRepository(session)
    circuit_map = await write_repo.get_or_create_circuits(tenant_id, building_id, meter_types)

    batch = RawIngestionBatch(
        tenant_id=tenant_id,
        building_id=building_id,
        ingestion_source=ingestion_source,
        raw_rows=raw_rows,
        circuit_map=circuit_map,
    )
    result = DataQualityGate(config=config).process_batch(batch)

    await write_repo.save_readings(result.readings)
    batch_id = await write_repo.create_batch_record(tenant_id, building_id, result)

    DataQualityEventPublisher(producer=event_publisher).publish_or_alert(result)

    return batch_id
