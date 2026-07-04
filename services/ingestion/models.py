from __future__ import annotations

import datetime
from uuid import UUID

from pydantic import BaseModel, Field

_STATUS_RANK = {"pass": 0, "degraded": 1, "quarantined": 2}


def worse_status(current: str, new: str) -> str:
    if _STATUS_RANK.get(new, 0) > _STATUS_RANK.get(current, 0):
        return new
    return current


class CircuitInfo(BaseModel):
    circuit_id: UUID
    circuit_type: str


class RawIngestionBatch(BaseModel):
    tenant_id: UUID
    building_id: UUID
    source_id: str = "default"
    ingestion_source: str  # "csv_upload" | "smart_meter_api"
    raw_rows: list[dict[str, str | float | None]]
    source_timezone: str = "UTC"
    circuit_map: dict[str, CircuitInfo]


class QualityIssue(BaseModel):
    issue_type: str
    severity: str  # "degraded" | "quarantined"
    circuit_id: UUID | None = None
    ts_start: datetime.datetime | None = None
    ts_end: datetime.datetime | None = None
    description: str


class NormalizedReading(BaseModel):
    tenant_id: UUID
    circuit_id: UUID
    ts: datetime.datetime
    kwh: float | None = None
    is_peak_hour: bool | None = None
    rolling_baseline_kwh: float | None = None
    data_quality_status: str = "pass"
    schema_version: str = "normalized_reading_v1"
    source_system: str
    ingestion_timestamp: datetime.datetime
    normalization_version: str


class BatchQualityResult(BaseModel):
    tenant_id: UUID
    building_id: UUID
    overall_status: str  # "pass" | "degraded" | "quarantined"
    readings: list[NormalizedReading]
    quality_issues: list[QualityIssue] = Field(default_factory=list)
    total_rows: int = 0
    pass_count: int = 0
    degraded_count: int = 0
    quarantined_count: int = 0
    ingestion_source: str = "csv_upload"


class DataQualityAlertPayload(BaseModel):
    tenant_id: UUID
    building_id: UUID
    alert_type: str  # "quarantined_batch" | "schema_drift"
    severity: str = "warning"
    message: str
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class PublishOutcome(BaseModel):
    published: bool
    alert: DataQualityAlertPayload | None = None
