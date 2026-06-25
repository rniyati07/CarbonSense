"""ENG-3a-1: Normalization service tests."""

from __future__ import annotations

import datetime
from uuid import UUID

import pytest

from services.ingestion.config import ColumnMappingConfig, DataQualityGateConfig
from services.ingestion.normalization import normalize_batch, resolve_columns
from tests.unit.services.ingestion.conftest import (
    HVAC_CIRCUIT_ID,
    LIGHT_CIRCUIT_ID,
    make_batch,
)


@pytest.mark.unit
class TestColumnMapping:
    def test_standard_aliases_resolved(self) -> None:
        mapping = ColumnMappingConfig()
        raw_rows = [{"meter_id": "M1", "timestamp": "2026-01-01T00:00:00", "kwh": "10"}]
        mapped, col_map = resolve_columns(raw_rows, mapping)
        assert col_map["meter_id"] == "circuit_id"
        assert col_map["timestamp"] == "ts"
        assert col_map["kwh"] == "kwh"
        assert mapped[0]["circuit_id"] == "M1"

    def test_alternative_aliases_resolved(self) -> None:
        mapping = ColumnMappingConfig()
        raw_rows = [{"sensor_id": "S1", "reading_time": "2026-01-01T00:00:00", "consumption": "5"}]
        mapped, col_map = resolve_columns(raw_rows, mapping)
        assert col_map["sensor_id"] == "circuit_id"
        assert col_map["reading_time"] == "ts"
        assert col_map["consumption"] == "kwh"

    def test_unknown_columns_preserved(self) -> None:
        mapping = ColumnMappingConfig()
        raw_rows = [{"meter_id": "M1", "timestamp": "t", "kwh": "1", "extra_col": "val"}]
        mapped, _ = resolve_columns(raw_rows, mapping)
        assert "extra_col" in mapped[0]

    def test_empty_rows(self) -> None:
        mapping = ColumnMappingConfig()
        mapped, col_map = resolve_columns([], mapping)
        assert mapped == []
        assert col_map == {}


@pytest.mark.unit
class TestCleanBatch:
    def test_clean_batch_all_pass(self, gate_config: DataQualityGateConfig) -> None:
        batch = make_batch("clean_batch.csv")
        readings, issues = normalize_batch(batch, gate_config)
        assert len(readings) > 0
        statuses = {r.data_quality_status for r in readings}
        assert statuses == {"pass"}, f"Expected all pass, got {statuses}"

    def test_timestamps_are_utc(self, gate_config: DataQualityGateConfig) -> None:
        batch = make_batch("clean_batch.csv")
        readings, _ = normalize_batch(batch, gate_config)
        for r in readings:
            assert r.ts.tzinfo is not None
            assert r.ts.utcoffset() == datetime.timedelta(0)

    def test_schema_version_set(self, gate_config: DataQualityGateConfig) -> None:
        batch = make_batch("clean_batch.csv")
        readings, _ = normalize_batch(batch, gate_config)
        for r in readings:
            assert r.schema_version == "normalized_reading_v1"

    def test_provenance_fields_set(self, gate_config: DataQualityGateConfig) -> None:
        batch = make_batch("clean_batch.csv")
        readings, _ = normalize_batch(batch, gate_config)
        for r in readings:
            assert r.source_system == "csv_upload"
            assert r.ingestion_timestamp is not None
            assert r.normalization_version == "v1.0.0"

    def test_circuit_ids_mapped(self, gate_config: DataQualityGateConfig) -> None:
        batch = make_batch("clean_batch.csv")
        readings, _ = normalize_batch(batch, gate_config)
        circuit_ids = {r.circuit_id for r in readings}
        assert HVAC_CIRCUIT_ID in circuit_ids
        assert LIGHT_CIRCUIT_ID in circuit_ids


@pytest.mark.unit
class TestGapHandling:
    def test_gap_within_bound_interpolated(self, gate_config: DataQualityGateConfig) -> None:
        batch = make_batch("gap_within_bound.csv")
        readings, issues = normalize_batch(batch, gate_config)
        hvac_readings = [r for r in readings if r.circuit_id == HVAC_CIRCUIT_ID]
        assert len(hvac_readings) >= 22
        gap_issues = [i for i in issues if i.issue_type == "gap_beyond_bound"]
        assert len(gap_issues) == 0

    def test_gap_beyond_bound_quarantined(self, gate_config: DataQualityGateConfig) -> None:
        batch = make_batch("gap_beyond_bound.csv")
        readings, issues = normalize_batch(batch, gate_config)
        gap_issues = [i for i in issues if i.issue_type == "gap_beyond_bound"]
        assert len(gap_issues) > 0
        quarantined = [r for r in readings if r.data_quality_status == "quarantined"]
        assert len(quarantined) > 0