"""ENG-3a-3: Bounds and schema drift tests."""

from __future__ import annotations

import datetime
from uuid import UUID

import pytest

from services.ingestion.bounds_and_drift import (
    check_bounds,
    check_schema_drift,
    compute_schema_fingerprint,
)
from services.ingestion.config import BoundsConfig, DataQualityGateConfig
from services.ingestion.models import NormalizedReading
from tests.unit.services.ingestion.conftest import HVAC_CIRCUIT_ID, TENANT_ID


def _make_reading(kwh: float, circuit_id: UUID = HVAC_CIRCUIT_ID) -> NormalizedReading:
    return NormalizedReading(
        tenant_id=TENANT_ID,
        circuit_id=circuit_id,
        ts=datetime.datetime(2026, 1, 15, 12, 0, tzinfo=datetime.timezone.utc),
        kwh=kwh,
        source_system="csv_upload",
        ingestion_timestamp=datetime.datetime.now(datetime.timezone.utc),
        normalization_version="v1.0.0",
    )


@pytest.mark.unit
class TestBoundsCheck:
    def test_value_within_bounds_passes(self) -> None:
        config = BoundsConfig()
        readings = [_make_reading(50.0)]
        issues = check_bounds(readings, config, {HVAC_CIRCUIT_ID: "hvac"})
        assert len(issues) == 0

    def test_negative_value_quarantined(self) -> None:
        config = BoundsConfig()
        readings = [_make_reading(-5.0)]
        issues = check_bounds(readings, config, {HVAC_CIRCUIT_ID: "hvac"})
        assert len(issues) == 1
        assert issues[0].issue_type == "implausible_value"
        assert issues[0].severity == "quarantined"

    def test_above_max_quarantined(self) -> None:
        config = BoundsConfig()
        readings = [_make_reading(9999.0)]
        issues = check_bounds(readings, config, {HVAC_CIRCUIT_ID: "hvac"})
        assert len(issues) == 1
        assert issues[0].severity == "quarantined"

    def test_bounds_vary_by_circuit_type(self) -> None:
        config = BoundsConfig()
        reading_250 = _make_reading(250.0)
        issues_hvac = check_bounds([reading_250], config, {HVAC_CIRCUIT_ID: "hvac"})
        issues_plug = check_bounds([reading_250], config, {HVAC_CIRCUIT_ID: "plug_load"})
        assert len(issues_hvac) == 0
        assert len(issues_plug) == 1

    def test_none_kwh_skipped(self) -> None:
        config = BoundsConfig()
        reading = _make_reading(0.0)
        reading.kwh = None
        issues = check_bounds([reading], config, {HVAC_CIRCUIT_ID: "hvac"})
        assert len(issues) == 0


@pytest.mark.unit
class TestSchemaFingerprint:
    def test_same_columns_same_fingerprint(self) -> None:
        fp1 = compute_schema_fingerprint(["meter_id", "timestamp", "kwh"])
        fp2 = compute_schema_fingerprint(["meter_id", "timestamp", "kwh"])
        assert fp1 == fp2

    def test_order_insensitive(self) -> None:
        fp1 = compute_schema_fingerprint(["meter_id", "timestamp", "kwh"])
        fp2 = compute_schema_fingerprint(["kwh", "meter_id", "timestamp"])
        assert fp1 == fp2

    def test_different_columns_different_fingerprint(self) -> None:
        fp1 = compute_schema_fingerprint(["meter_id", "timestamp", "kwh"])
        fp2 = compute_schema_fingerprint(["sensor_id", "reading_time", "consumption"])
        assert fp1 != fp2


@pytest.mark.unit
class TestSchemaDrift:
    def test_matching_schema_no_drift(self) -> None:
        config = DataQualityGateConfig()
        issues = check_schema_drift(
            ["meter_id", "timestamp", "kwh", "circuit_type"],
            "default",
            config,
        )
        assert len(issues) == 0

    def test_extra_columns_degraded(self) -> None:
        config = DataQualityGateConfig()
        issues = check_schema_drift(
            ["meter_id", "timestamp", "kwh", "circuit_type", "extra_field"],
            "default",
            config,
        )
        assert len(issues) == 1
        assert issues[0].severity == "degraded"
        assert issues[0].issue_type == "schema_drift"

    def test_missing_required_quarantined(self) -> None:
        config = DataQualityGateConfig()
        issues = check_schema_drift(
            ["sensor_id", "reading_time", "consumption", "device_type"],
            "default",
            config,
        )
        drift_issues = [i for i in issues if i.issue_type == "schema_drift"]
        assert len(drift_issues) > 0

    def test_drift_fixture(self) -> None:
        config = DataQualityGateConfig()
        issues = check_schema_drift(
            ["sensor_id", "reading_time", "consumption", "device_type"],
            "default",
            config,
        )
        assert len(issues) > 0