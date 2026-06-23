from __future__ import annotations

from dataclasses import dataclass

from orchestration.events.kafka.schemas.base import BaseEvent


@dataclass(frozen=True)
class BuildingDataArrivedEvent(BaseEvent):
    """Published when the Data Quality Gate clears a batch at pass/degraded.

    TRD v2.0 section 3.1: a quarantined-only batch does NOT trigger this event.
    """

    data_quality_status: str  # "pass" | "degraded"
    batch_row_count: int
    ingestion_source: str  # "csv_upload" | "smart_meter_api"
