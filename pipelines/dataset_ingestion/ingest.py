"""ENG-6a — public-dataset bulk ingestion orchestration.

Drives services.ingestion.orchestrator.ingest_raw_rows() (the exact write
path CSV upload and the smart-meter push receiver already use, ENG-5b/5d)
over a public dataset file, chunk by chunk, through the same
DataQualityGate + normalized_readings persistence -- no separate ingestion
logic for "real dataset" vs. "customer upload." What's specific to this
module is orchestration: chunked reads, per-chunk sessions/transactions,
and a bulk-backfill event-publishing default (see NullEventPublisher).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

from orchestration.events.kafka.producer import EventPublisher
from orchestration.events.kafka.schemas.base import BaseEvent
from pipelines.dataset_ingestion.loader import iter_csv_chunks
from pipelines.dataset_ingestion.public_dataset_config import get_public_dataset_source
from services.ingestion.config import DataQualityGateConfig, SourceConfig
from services.ingestion.orchestrator import ingest_raw_rows
from services.ingestion.repository import IngestionWriteRepository
from shared.auth.tenant_context import tenant_scope
from shared.database import get_session_factory

logger = logging.getLogger(__name__)


class NullEventPublisher:
    """No-op EventPublisher for bulk historical backfill.

    Publishing building.data.arrived once per chunk of a months-long
    public dataset would fan out into thousands of live
    AnalysisPipelineWorkflow executions -- appropriate for a real
    customer upload (ENG-5's use case), not for populating training
    history. Implements the same EventPublisher Protocol
    (orchestration/events/kafka/producer.py) so ingest_raw_rows() needs
    no special-casing; callers that DO want live analysis triggered from
    a dataset backfill can pass a real CarbonSenseKafkaProducer instead.
    """

    def publish(self, topic: str, event: BaseEvent) -> None:
        logger.debug("NullEventPublisher: suppressed publish to %s", topic)

    def flush(self, timeout: float = 5.0) -> int:
        return 0


@dataclass
class DatasetIngestionSummary:
    source_id: str
    file_path: str
    tenant_id: UUID
    building_id: UUID
    chunks_processed: int = 0
    total_rows: int = 0
    pass_count: int = 0
    degraded_count: int = 0
    quarantined_count: int = 0
    batch_ids: list[UUID] = field(default_factory=list)


async def ingest_public_dataset(
    file_path: str | Path,
    source_id: str,
    tenant_id: UUID,
    building_id: UUID,
    chunk_size: int = 5000,
    event_publisher: EventPublisher | None = None,
) -> DatasetIngestionSummary:
    """Ingest a public dataset CSV into normalized_readings for one
    (tenant, building), reusing the identical DataQualityGate write path
    CSV upload and the smart-meter receiver already use.

    Each chunk gets its own tenant-scoped session/transaction so a very
    large file doesn't hold one transaction open for its entire runtime,
    and a failure partway through leaves earlier chunks durably committed
    rather than rolling back the whole ingest.
    """
    publisher = event_publisher or NullEventPublisher()
    config = DataQualityGateConfig(
        sources={
            source_id: get_public_dataset_source(source_id),
            "default": SourceConfig(source_id="default"),
        }
    )

    summary = DatasetIngestionSummary(
        source_id=source_id,
        file_path=str(file_path),
        tenant_id=tenant_id,
        building_id=building_id,
    )
    factory = get_session_factory()

    for chunk in iter_csv_chunks(file_path, chunk_size=chunk_size):
        async with factory() as session, tenant_scope(session, tenant_id):
            batch_id = await ingest_raw_rows(
                session=session,
                tenant_id=tenant_id,
                building_id=building_id,
                raw_rows=chunk,
                ingestion_source=f"public_dataset_{source_id}",
                event_publisher=publisher,
                source_id=source_id,
                config=config,
            )
            batch = await IngestionWriteRepository(session).get_batch(tenant_id, batch_id)
            await session.commit()

        summary.chunks_processed += 1
        summary.total_rows += len(chunk)
        summary.batch_ids.append(batch_id)
        if batch is not None:
            summary.pass_count += batch["pass_count"]
            summary.degraded_count += batch["degraded_count"]
            summary.quarantined_count += batch["quarantined_count"]

        logger.info(
            "ingest_public_dataset: chunk %d complete, %d rows, batch_id=%s",
            summary.chunks_processed,
            len(chunk),
            batch_id,
        )

    return summary
