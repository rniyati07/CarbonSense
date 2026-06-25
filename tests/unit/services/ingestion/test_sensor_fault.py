"""ENG-3a-2: Sensor fault detection tests."""

from __future__ import annotations

import datetime
from uuid import UUID

import pytest

from services.ingestion.config import DataQualityGateConfig, SensorFaultConfig
from services.ingestion.models import NormalizedReading
from services.ingestion.sensor_fault import (
    detect_dropout,
    detect_sensor_faults,
    detect_stuck_at_value,
)
from tests.unit.services.ingestion.conftest import (
    HVAC_CIRCUIT_ID,
    TENANT_ID,
    make_batch,
)
from services.ingestion.normalization import normalize_batch


def _make_reading(
    hour: int,
    kwh: float,
    circuit_id: UUID = HVAC_CIRCUIT_ID,
) -> NormalizedReading:
    return NormalizedReading(
        tenant_id=TENANT_ID,
        circuit_id=circuit_id,
        ts=datetime.datetime(2026, 1, 15, hour, 0, tzinfo=datetime.timezone.utc),
        kwh=kwh,
        source_system="csv_upload",
        ingestion_timestamp=datetime.datetime.now(datetime.timezone.utc),
        normalization_version="v1.0.0",
    )


@pytest.mark.unit
class TestStuckAtValue:
    def test_stuck_hvac_detected(self) -> None:
        readings = [_make_reading(h, 25.0) for h in range(24)]
        config = SensorFaultConfig()
        issues = detect_stuck_at_value(
            readings, HVAC_CIRCUIT_ID, "hvac", config
        )
        assert len(issues) > 0
        assert issues[0].issue_type == "stuck_at_value"

    def test_varying_values_no_stuck(self) -> None:
        readings = [_make_reading(h, 10.0 + h * 2.5) for h in range(24)]
        config = SensorFaultConfig()
        issues = detect_stuck_at_value(
            readings, HVAC_CIRCUIT_ID, "hvac", config
        )
        assert len(issues) == 0

    def test_circuit_type_affects_threshold(self) -> None:
        readings = [_make_reading(h, 25.0) for h in range(24)]
        config = SensorFaultConfig()
        hvac_issues = detect_stuck_at_value(
            readings, HVAC_CIRCUIT_ID, "hvac", config
        )
        plug_issues = detect_stuck_at_value(
            readings, HVAC_CIRCUIT_ID, "plug_load", config
        )
        assert len(hvac_issues) > 0
        assert len(plug_issues) > 0
        assert hvac_issues[0].severity == "degraded"

    def test_stuck_fixture_detected(self, gate_config: DataQualityGateConfig) -> None:
        batch = make_batch("stuck_at_value.csv")
        readings, _ = normalize_batch(batch, gate_config)
        circuit_types = {HVAC_CIRCUIT_ID: "hvac"}
        issues = detect_sensor_faults(
            readings, circuit_types, "csv_upload", gate_config.sensor_fault
        )
        stuck_issues = [i for i in issues if i.issue_type == "stuck_at_value"]
        assert len(stuck_issues) > 0


@pytest.mark.unit
class TestDropout:
    def test_dropout_detected_for_large_gap(self) -> None:
        timestamps = [
            datetime.datetime(2026, 1, 15, h, 0, tzinfo=datetime.timezone.utc)
            for h in [0, 1, 2, 3, 10, 11, 12]
        ]
        config = SensorFaultConfig()
        issues = detect_dropout(
            timestamps, HVAC_CIRCUIT_ID, "csv_upload", config
        )
        assert len(issues) > 0
        assert issues[0].issue_type == "dropout"

    def test_no_dropout_for_regular_intervals(self) -> None:
        timestamps = [
            datetime.datetime(2026, 1, 15, h, 0, tzinfo=datetime.timezone.utc)
            for h in range(24)
        ]
        config = SensorFaultConfig()
        issues = detect_dropout(
            timestamps, HVAC_CIRCUIT_ID, "csv_upload", config
        )
        assert len(issues) == 0

    def test_dropout_fixture(self, gate_config: DataQualityGateConfig) -> None:
        from services.ingestion.quality_gate import _extract_raw_timestamps

        batch = make_batch("dropout.csv")
        raw_ts = _extract_raw_timestamps(batch, gate_config)
        hvac_ts = raw_ts.get(HVAC_CIRCUIT_ID, [])
        config = gate_config.sensor_fault
        issues = detect_dropout(
            hvac_ts, HVAC_CIRCUIT_ID, "csv_upload", config
        )
        assert len(issues) > 0