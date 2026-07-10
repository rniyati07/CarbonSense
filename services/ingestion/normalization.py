from __future__ import annotations

import datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from services.ingestion.config import ColumnMappingConfig, DataQualityGateConfig
from services.ingestion.models import (
    NormalizedReading,
    QualityIssue,
    RawIngestionBatch,
    worse_status,
)


def _resolve_column(raw_name: str, mapping: ColumnMappingConfig) -> str | None:
    lower = raw_name.strip().lower()
    alias_groups: list[tuple[str, list[str]]] = [
        ("circuit_id", [a.lower() for a in mapping.circuit_id_aliases]),
        ("ts", [a.lower() for a in mapping.timestamp_aliases]),
        ("kwh", [a.lower() for a in mapping.kwh_aliases]),
        ("circuit_type", [a.lower() for a in mapping.circuit_type_aliases]),
    ]
    for canonical, aliases in alias_groups:
        if lower in aliases:
            return canonical
    return None


def resolve_columns(
    raw_rows: list[dict[str, Any]],
    mapping: ColumnMappingConfig,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    if not raw_rows:
        return [], {}

    raw_columns = list(raw_rows[0].keys())
    col_map: dict[str, str] = {}
    for raw_col in raw_columns:
        canonical = _resolve_column(raw_col, mapping)
        if canonical is not None:
            col_map[raw_col] = canonical

    mapped_rows: list[dict[str, Any]] = []
    for row in raw_rows:
        mapped: dict[str, Any] = {}
        for raw_col, value in row.items():
            canonical = col_map.get(raw_col)
            if canonical is not None:
                mapped[canonical] = value
            else:
                mapped[raw_col] = value
        mapped_rows.append(mapped)

    return mapped_rows, col_map


def normalize_timestamps(
    df: pd.DataFrame,
    source_timezone: str,
) -> pd.DataFrame:
    tz = ZoneInfo(source_timezone)
    parsed: list[datetime.datetime] = []
    for val in df["ts"]:
        ts = val if isinstance(val, datetime.datetime) else pd.Timestamp(str(val)).to_pydatetime()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=tz)
        parsed.append(ts.astimezone(datetime.UTC))
    df = df.copy()
    df["ts"] = parsed
    return df


def _detect_gaps(
    timestamps: list[datetime.datetime],
    max_gap_minutes: int,
) -> list[tuple[datetime.datetime, datetime.datetime, int]]:
    gaps: list[tuple[datetime.datetime, datetime.datetime, int]] = []
    for i in range(1, len(timestamps)):
        delta = timestamps[i] - timestamps[i - 1]
        gap_min = int(delta.total_seconds() / 60)
        expected = 60
        if gap_min > expected:
            gaps.append((timestamps[i - 1], timestamps[i], gap_min))
    return gaps


def _resample_circuit(
    circuit_df: pd.DataFrame,
    gap_config: Any,
    circuit_id: UUID,
) -> tuple[pd.DataFrame, list[QualityIssue], dict[str, str]]:
    issues: list[QualityIssue] = []
    row_statuses: dict[str, str] = {}

    circuit_df = circuit_df.sort_values("ts").copy()
    circuit_df["ts_idx"] = pd.to_datetime([t.isoformat() for t in circuit_df["ts"]], utc=True)
    circuit_df = circuit_df.set_index("ts_idx")

    ts_min = circuit_df.index.min().floor("h")
    ts_max = circuit_df.index.max().ceil("h")
    hourly_index = pd.date_range(ts_min, ts_max, freq="h", inclusive="left")

    resampled = circuit_df["kwh"].resample("1h").sum(min_count=1)
    resampled = resampled.reindex(hourly_index)

    gaps = resampled[resampled.isna()]
    if not gaps.empty:
        gap_starts: list[pd.Timestamp] = []
        gap_ends: list[pd.Timestamp] = []
        in_gap = False
        gap_start: pd.Timestamp | None = None

        for ts in hourly_index:
            if pd.isna(resampled.get(ts)):
                if not in_gap:
                    in_gap = True
                    gap_start = ts
            else:
                if in_gap and gap_start is not None:
                    gap_starts.append(gap_start)
                    gap_ends.append(ts)
                    in_gap = False
                    gap_start = None
        if in_gap and gap_start is not None:
            gap_starts.append(gap_start)
            gap_ends.append(hourly_index[-1] + pd.Timedelta(hours=1))

        for gs, ge in zip(gap_starts, gap_ends, strict=False):
            gap_minutes = int((ge - gs).total_seconds() / 60)
            if gap_minutes <= gap_config.max_interpolation_gap_minutes:
                resampled.loc[gs:ge] = resampled.loc[gs:ge].interpolate(method="linear")
            else:
                for ts in hourly_index[(hourly_index >= gs) & (hourly_index < ge)]:
                    ts_key = str(ts)
                    row_statuses[ts_key] = worse_status(
                        row_statuses.get(ts_key, "pass"), "quarantined"
                    )
                issues.append(
                    QualityIssue(
                        issue_type="gap_beyond_bound",
                        severity="quarantined",
                        circuit_id=circuit_id,
                        ts_start=gs.to_pydatetime().replace(tzinfo=datetime.UTC),
                        ts_end=ge.to_pydatetime().replace(tzinfo=datetime.UTC),
                        description=(
                            f"Gap of {gap_minutes} minutes exceeds "
                            f"max_interpolation_gap_minutes={gap_config.max_interpolation_gap_minutes}"
                        ),
                    )
                )

    result = pd.DataFrame({"kwh": resampled}, index=hourly_index)
    result.index.name = "ts"
    return result, issues, row_statuses


def _rolling_zscore_guard(
    hourly_kwh: pd.Series,  # type: ignore[type-arg]
    circuit_id: UUID,
    zscore_threshold: float,
    window_size: int,
) -> tuple[list[QualityIssue], dict[str, str]]:
    issues: list[QualityIssue] = []
    row_statuses: dict[str, str] = {}

    if len(hourly_kwh) < window_size:
        return issues, row_statuses

    rolling_mean = hourly_kwh.rolling(
        window=window_size, min_periods=max(1, window_size // 2)
    ).mean()
    rolling_std = hourly_kwh.rolling(window=window_size, min_periods=max(1, window_size // 2)).std()

    with np.errstate(divide="ignore", invalid="ignore"):
        zscore = (hourly_kwh - rolling_mean) / rolling_std

    zscore = zscore.fillna(0.0)
    outliers = zscore.abs() > zscore_threshold

    for ts, is_outlier in outliers.items():
        if is_outlier:
            ts_key = str(ts)
            row_statuses[ts_key] = worse_status(row_statuses.get(ts_key, "pass"), "degraded")
            ts_dt = pd.Timestamp(ts).to_pydatetime()
            if ts_dt.tzinfo is None:
                ts_dt = ts_dt.replace(tzinfo=datetime.UTC)
            issues.append(
                QualityIssue(
                    issue_type="outlier",
                    severity="degraded",
                    circuit_id=circuit_id,
                    ts_start=ts_dt,
                    ts_end=ts_dt + datetime.timedelta(hours=1),
                    description=(
                        f"Rolling Z-score {float(zscore[ts]):.2f} "
                        f"exceeds threshold {zscore_threshold}"
                    ),
                )
            )

    return issues, row_statuses


def normalize_batch(
    batch: RawIngestionBatch,
    config: DataQualityGateConfig,
) -> tuple[list[NormalizedReading], list[QualityIssue]]:
    source_config = config.get_source(batch.source_id)
    now = datetime.datetime.now(datetime.UTC)

    mapped_rows, _col_map = resolve_columns(batch.raw_rows, source_config.column_mapping)

    if not mapped_rows:
        return [], []

    df = pd.DataFrame(mapped_rows)

    required = {"ts", "kwh"}
    missing = required - set(df.columns)
    if missing:
        return [], [
            QualityIssue(
                issue_type="missing_columns",
                severity="quarantined",
                description=f"Required columns missing after mapping: {missing}",
            )
        ]

    df = normalize_timestamps(df, batch.source_timezone)
    df["kwh"] = pd.to_numeric(df["kwh"], errors="coerce")

    raw_circuit_col = "circuit_id" if "circuit_id" in df.columns else None
    if raw_circuit_col is None:
        return [], [
            QualityIssue(
                issue_type="missing_columns",
                severity="quarantined",
                description="No circuit identifier column found after mapping",
            )
        ]

    all_readings: list[NormalizedReading] = []
    all_issues: list[QualityIssue] = []
    all_row_statuses: dict[tuple[str, str], str] = {}

    interpolation_count = 0
    total_count = 0

    for raw_meter_id, group in df.groupby(raw_circuit_col, sort=False):
        meter_str = str(raw_meter_id)
        circuit_info = batch.circuit_map.get(meter_str)
        if circuit_info is None:
            all_issues.append(
                QualityIssue(
                    issue_type="unmapped_circuit",
                    severity="quarantined",
                    description=f"Raw meter ID '{meter_str}' not found in circuit_map",
                )
            )
            continue

        circuit_id = circuit_info.circuit_id
        original_count = len(group)

        resampled_df, gap_issues, gap_statuses = _resample_circuit(group, config.gap, circuit_id)
        all_issues.extend(gap_issues)

        resampled_count = int(resampled_df["kwh"].notna().sum())
        interpolation_count += max(0, resampled_count - original_count)
        total_count += resampled_count

        outlier_issues, outlier_statuses = _rolling_zscore_guard(
            resampled_df["kwh"].dropna(),
            circuit_id,
            config.outlier.zscore_threshold,
            config.outlier.window_size,
        )
        all_issues.extend(outlier_issues)

        for ts_idx, row in resampled_df.iterrows():
            ts_key = str(ts_idx)
            status = "pass"
            status = worse_status(status, gap_statuses.get(ts_key, "pass"))
            status = worse_status(status, outlier_statuses.get(ts_key, "pass"))

            ts_dt = pd.Timestamp(ts_idx).to_pydatetime()
            if ts_dt.tzinfo is None:
                ts_dt = ts_dt.replace(tzinfo=datetime.UTC)

            kwh_val = float(row["kwh"]) if pd.notna(row["kwh"]) else None

            all_row_statuses[(str(circuit_id), ts_key)] = status
            all_readings.append(
                NormalizedReading(
                    tenant_id=batch.tenant_id,
                    circuit_id=circuit_id,
                    ts=ts_dt,
                    kwh=kwh_val,
                    data_quality_status=status,
                    source_system=batch.ingestion_source,
                    ingestion_timestamp=now,
                    normalization_version=config.normalization_version,
                )
            )

    if total_count > 0:
        ratio = interpolation_count / total_count
        if ratio > config.gap.degraded_interpolation_ratio:
            for reading in all_readings:
                if reading.data_quality_status == "pass":
                    reading.data_quality_status = "degraded"
            all_issues.append(
                QualityIssue(
                    issue_type="high_interpolation_ratio",
                    severity="degraded",
                    description=(
                        f"Interpolated {interpolation_count}/{total_count} "
                        f"({ratio:.1%}) exceeds threshold "
                        f"{config.gap.degraded_interpolation_ratio:.0%}"
                    ),
                )
            )

    return all_readings, all_issues
