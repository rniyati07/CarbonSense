from __future__ import annotations

import datetime
from collections import defaultdict
from uuid import UUID

import numpy as np

from services.ingestion.config import SensorFaultConfig
from services.ingestion.models import NormalizedReading, QualityIssue


def detect_stuck_at_value(
    readings: list[NormalizedReading],
    circuit_id: UUID,
    circuit_type: str,
    config: SensorFaultConfig,
) -> list[QualityIssue]:
    thresholds = config.stuck_thresholds.get(circuit_type, config.default_stuck_thresholds)
    sorted_readings = sorted(
        [r for r in readings if r.kwh is not None],
        key=lambda r: r.ts,
    )
    if len(sorted_readings) < thresholds.window_size:
        return []

    kwh_values = np.array([r.kwh for r in sorted_readings], dtype=float)
    timestamps = [r.ts for r in sorted_readings]

    issues: list[QualityIssue] = []
    stuck_start: int | None = None

    for i in range(thresholds.window_size - 1, len(kwh_values)):
        window = kwh_values[i - thresholds.window_size + 1 : i + 1]
        variance = float(np.var(window))

        if variance <= thresholds.variance_threshold:
            if stuck_start is None:
                stuck_start = i - thresholds.window_size + 1
        else:
            if stuck_start is not None:
                _maybe_add_stuck_issue(
                    issues,
                    stuck_start,
                    i - 1,
                    timestamps,
                    circuit_id,
                    circuit_type,
                    thresholds.duration_threshold_hours,
                    kwh_values,
                )
                stuck_start = None

    if stuck_start is not None:
        _maybe_add_stuck_issue(
            issues,
            stuck_start,
            len(timestamps) - 1,
            timestamps,
            circuit_id,
            circuit_type,
            thresholds.duration_threshold_hours,
            kwh_values,
        )

    return issues


def _maybe_add_stuck_issue(
    issues: list[QualityIssue],
    start_idx: int,
    end_idx: int,
    timestamps: list[datetime.datetime],
    circuit_id: UUID,
    circuit_type: str,
    duration_threshold_hours: int,
    kwh_values: np.ndarray,  # type: ignore[type-arg]
) -> None:
    ts_start = timestamps[start_idx]
    ts_end = timestamps[end_idx]
    duration_hours = (ts_end - ts_start).total_seconds() / 3600

    if duration_hours >= duration_threshold_hours:
        stuck_value = float(kwh_values[start_idx])
        severity = "quarantined" if circuit_type == "main_feed" else "degraded"
        issues.append(
            QualityIssue(
                issue_type="stuck_at_value",
                severity=severity,
                circuit_id=circuit_id,
                ts_start=ts_start,
                ts_end=ts_end,
                description=(
                    f"Stuck at {stuck_value:.2f} kWh for {duration_hours:.1f}h "
                    f"(threshold: {duration_threshold_hours}h for {circuit_type})"
                ),
            )
        )


def detect_dropout(
    raw_timestamps: list[datetime.datetime],
    circuit_id: UUID,
    ingestion_source: str,
    config: SensorFaultConfig,
) -> list[QualityIssue]:
    expected_minutes = config.expected_intervals.get(
        ingestion_source, config.default_expected_interval_minutes
    )
    max_gap_minutes = expected_minutes * config.dropout_tolerance_factor

    sorted_ts = sorted(raw_timestamps)
    if len(sorted_ts) < 2:
        return []

    issues: list[QualityIssue] = []
    for i in range(1, len(sorted_ts)):
        delta_minutes = (sorted_ts[i] - sorted_ts[i - 1]).total_seconds() / 60

        if delta_minutes > max_gap_minutes:
            issues.append(
                QualityIssue(
                    issue_type="dropout",
                    severity="degraded",
                    circuit_id=circuit_id,
                    ts_start=sorted_ts[i - 1],
                    ts_end=sorted_ts[i],
                    description=(
                        f"Reporting gap of {delta_minutes:.0f} min exceeds "
                        f"{max_gap_minutes:.0f} min "
                        f"({config.dropout_tolerance_factor}x expected "
                        f"{expected_minutes} min for {ingestion_source})"
                    ),
                )
            )

    return issues


def detect_sensor_faults(
    readings: list[NormalizedReading],
    circuit_types: dict[UUID, str],
    ingestion_source: str,
    config: SensorFaultConfig,
    raw_timestamps_by_circuit: dict[UUID, list[datetime.datetime]] | None = None,
) -> list[QualityIssue]:
    by_circuit: dict[UUID, list[NormalizedReading]] = defaultdict(list)
    for r in readings:
        by_circuit[r.circuit_id].append(r)

    all_issues: list[QualityIssue] = []
    for circuit_id, circuit_readings in by_circuit.items():
        circuit_type = circuit_types.get(circuit_id, "unknown")

        stuck_issues = detect_stuck_at_value(circuit_readings, circuit_id, circuit_type, config)
        all_issues.extend(stuck_issues)

        if raw_timestamps_by_circuit and circuit_id in raw_timestamps_by_circuit:
            dropout_ts = raw_timestamps_by_circuit[circuit_id]
        else:
            dropout_ts = [r.ts for r in circuit_readings if r.kwh is not None]
        dropout_issues = detect_dropout(dropout_ts, circuit_id, ingestion_source, config)
        all_issues.extend(dropout_issues)

    return all_issues
