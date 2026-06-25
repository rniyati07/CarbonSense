from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING
from uuid import UUID

from services.ingestion.config import BoundsConfig, DataQualityGateConfig
from services.ingestion.models import NormalizedReading, QualityIssue

if TYPE_CHECKING:
    from services.ingestion.bounds_repository import BoundsRepository


def check_bounds(
    readings: list[NormalizedReading],
    config: BoundsConfig,
    circuit_types: dict[UUID, str],
    bounds_repo: BoundsRepository | None = None,
) -> list[QualityIssue]:
    if bounds_repo is not None:
        config = bounds_repo.get()
    issues: list[QualityIssue] = []

    for reading in readings:
        if reading.kwh is None:
            continue

        circuit_type = circuit_types.get(reading.circuit_id, "unknown")
        bounds = config.circuit_type_bounds.get(circuit_type, config.default_bounds)

        if reading.kwh < bounds.min_kwh or reading.kwh > bounds.max_kwh:
            issues.append(QualityIssue(
                issue_type="implausible_value",
                severity="quarantined",
                circuit_id=reading.circuit_id,
                ts_start=reading.ts,
                ts_end=reading.ts,
                description=(
                    f"Value {reading.kwh:.2f} kWh outside bounds "
                    f"[{bounds.min_kwh}, {bounds.max_kwh}] "
                    f"for circuit_type={circuit_type}"
                ),
            ))

    return issues


def compute_schema_fingerprint(
    columns: list[str],
    column_types: dict[str, str] | None = None,
) -> str:
    normalized = sorted(c.strip().lower() for c in columns)
    payload: dict[str, object] = {"columns": normalized}
    if column_types:
        payload["types"] = {
            k.strip().lower(): v for k, v in sorted(column_types.items())
        }
    raw = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def check_schema_drift(
    raw_columns: list[str],
    source_id: str,
    config: DataQualityGateConfig,
) -> list[QualityIssue]:
    source_config = config.get_source(source_id)

    if not source_config.expected_columns:
        return []

    expected_set = {c.strip().lower() for c in source_config.expected_columns}
    actual_set = {c.strip().lower() for c in raw_columns}

    missing = expected_set - actual_set
    extra = actual_set - expected_set

    issues: list[QualityIssue] = []

    required_set = {c.strip().lower() for c in source_config.required_fields}
    missing_required = required_set & missing

    if missing_required:
        issues.append(QualityIssue(
            issue_type="schema_drift",
            severity="quarantined",
            description=(
                f"Required columns missing for source '{source_id}': "
                f"{sorted(missing_required)}"
            ),
        ))
    elif missing or extra:
        changes: list[str] = []
        if missing:
            changes.append(f"missing={sorted(missing)}")
        if extra:
            changes.append(f"unexpected={sorted(extra)}")
        issues.append(QualityIssue(
            issue_type="schema_drift",
            severity="degraded",
            description=(
                f"Schema drift detected for source '{source_id}': "
                + ", ".join(changes)
            ),
        ))

    return issues


def check_bounds_and_drift(
    readings: list[NormalizedReading],
    raw_columns: list[str],
    source_id: str,
    circuit_types: dict[UUID, str],
    config: DataQualityGateConfig,
    bounds_repo: BoundsRepository | None = None,
) -> list[QualityIssue]:
    bound_issues = check_bounds(readings, config.bounds, circuit_types, bounds_repo=bounds_repo)
    drift_issues = check_schema_drift(raw_columns, source_id, config)
    return bound_issues + drift_issues