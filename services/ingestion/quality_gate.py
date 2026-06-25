from __future__ import annotations

import datetime
from collections import defaultdict
from typing import TYPE_CHECKING, Any
from uuid import UUID
from zoneinfo import ZoneInfo

from services.ingestion.bounds_and_drift import check_bounds_and_drift
from services.ingestion.config import DataQualityGateConfig
from services.ingestion.models import (
    BatchQualityResult,
    NormalizedReading,
    QualityIssue,
    RawIngestionBatch,
    worse_status,
)
from services.ingestion.normalization import normalize_batch, resolve_columns
from services.ingestion.sensor_fault import detect_sensor_faults

import pandas as pd

if TYPE_CHECKING:
    from services.ingestion.bounds_repository import BoundsRepository


def _extract_raw_timestamps(
    batch: RawIngestionBatch,
    config: DataQualityGateConfig,
) -> dict[UUID, list[datetime.datetime]]:
    source_config = config.get_source(batch.source_id)
    mapped_rows, _ = resolve_columns(batch.raw_rows, source_config.column_mapping)
    tz = ZoneInfo(batch.source_timezone)

    result: dict[UUID, list[datetime.datetime]] = defaultdict(list)
    for row in mapped_rows:
        raw_circuit = str(row.get("circuit_id", ""))
        circuit_info = batch.circuit_map.get(raw_circuit)
        if circuit_info is None:
            continue
        ts_raw = row.get("ts")
        if ts_raw is None:
            continue
        try:
            if isinstance(ts_raw, datetime.datetime):
                ts = ts_raw
            else:
                ts = pd.Timestamp(str(ts_raw)).to_pydatetime()
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=tz)
            ts = ts.astimezone(datetime.timezone.utc)
            result[circuit_info.circuit_id].append(ts)
        except (ValueError, TypeError):
            continue
    return dict(result)


class DataQualityGate:
    def __init__(
        self,
        config: DataQualityGateConfig | None = None,
        bounds_repo: BoundsRepository | None = None,
    ) -> None:
        self._config = config or DataQualityGateConfig()
        self._bounds_repo = bounds_repo

    @property
    def config(self) -> DataQualityGateConfig:
        return self._config

    def process_batch(self, batch: RawIngestionBatch) -> BatchQualityResult:
        raw_columns = list(batch.raw_rows[0].keys()) if batch.raw_rows else []
        circuit_types = {
            info.circuit_id: info.circuit_type
            for info in batch.circuit_map.values()
        }

        raw_ts_by_circuit = _extract_raw_timestamps(batch, self._config)

        readings, norm_issues = normalize_batch(batch, self._config)

        fault_issues = detect_sensor_faults(
            readings,
            circuit_types,
            batch.ingestion_source,
            self._config.sensor_fault,
            raw_timestamps_by_circuit=raw_ts_by_circuit,
        )

        bd_issues = check_bounds_and_drift(
            readings,
            raw_columns,
            batch.source_id,
            circuit_types,
            self._config,
            bounds_repo=self._bounds_repo,
        )

        all_issues = norm_issues + fault_issues + bd_issues

        readings = _apply_issues(readings, fault_issues + bd_issues)

        overall = _compute_batch_status(readings)

        pass_count = sum(1 for r in readings if r.data_quality_status == "pass")
        degraded_count = sum(1 for r in readings if r.data_quality_status == "degraded")
        quarantined_count = sum(1 for r in readings if r.data_quality_status == "quarantined")

        return BatchQualityResult(
            tenant_id=batch.tenant_id,
            building_id=batch.building_id,
            overall_status=overall,
            readings=readings,
            quality_issues=all_issues,
            total_rows=len(readings),
            pass_count=pass_count,
            degraded_count=degraded_count,
            quarantined_count=quarantined_count,
            ingestion_source=batch.ingestion_source,
        )


def _apply_issues(
    readings: list[NormalizedReading],
    issues: list[QualityIssue],
) -> list[NormalizedReading]:
    for issue in issues:
        for reading in readings:
            if _issue_affects_reading(issue, reading):
                reading.data_quality_status = worse_status(
                    reading.data_quality_status, issue.severity
                )
    return readings


def _issue_affects_reading(issue: QualityIssue, reading: NormalizedReading) -> bool:
    if issue.circuit_id is not None and issue.circuit_id != reading.circuit_id:
        return False

    if issue.circuit_id is None:
        return True

    if issue.ts_start is not None and issue.ts_end is not None:
        return issue.ts_start <= reading.ts <= issue.ts_end

    if issue.ts_start is not None:
        return reading.ts == issue.ts_start

    return True


def _compute_batch_status(readings: list[NormalizedReading]) -> str:
    if not readings:
        return "quarantined"

    statuses = [r.data_quality_status for r in readings]

    if all(s == "quarantined" for s in statuses):
        return "quarantined"
    if all(s == "pass" for s in statuses):
        return "pass"
    return "degraded"