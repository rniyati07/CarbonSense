"""ENG-3a integration: Full quality gate pipeline tests."""

from __future__ import annotations

import pytest

from services.ingestion.config import DataQualityGateConfig
from services.ingestion.quality_gate import DataQualityGate
from tests.unit.services.ingestion.conftest import (
    make_batch,
)


@pytest.mark.unit
class TestQualityGateCleanBatch:
    def test_clean_batch_passes(self) -> None:
        gate = DataQualityGate()
        batch = make_batch("clean_batch.csv")
        result = gate.process_batch(batch)
        assert result.overall_status == "pass"
        assert result.pass_count > 0
        assert result.quarantined_count == 0

    def test_clean_batch_has_readings(self) -> None:
        gate = DataQualityGate()
        batch = make_batch("clean_batch.csv")
        result = gate.process_batch(batch)
        assert result.total_rows > 0
        assert len(result.readings) == result.total_rows


@pytest.mark.unit
class TestQualityGateGaps:
    def test_gap_within_bound_not_quarantined(self) -> None:
        gate = DataQualityGate()
        batch = make_batch("gap_within_bound.csv")
        result = gate.process_batch(batch)
        assert result.overall_status in ("pass", "degraded")

    def test_gap_beyond_bound_produces_quarantined_readings(self) -> None:
        gate = DataQualityGate()
        batch = make_batch("gap_beyond_bound.csv")
        result = gate.process_batch(batch)
        assert result.quarantined_count > 0
        assert result.overall_status in ("degraded", "quarantined")
        gap_issues = [i for i in result.quality_issues if i.issue_type == "gap_beyond_bound"]
        assert len(gap_issues) > 0


@pytest.mark.unit
class TestQualityGateSensorFaults:
    def test_stuck_at_value_detected(self) -> None:
        gate = DataQualityGate()
        batch = make_batch("stuck_at_value.csv")
        result = gate.process_batch(batch)
        stuck_issues = [i for i in result.quality_issues if i.issue_type == "stuck_at_value"]
        assert len(stuck_issues) > 0
        assert result.overall_status in ("degraded", "quarantined")

    def test_dropout_detected(self) -> None:
        gate = DataQualityGate()
        batch = make_batch("dropout.csv")
        result = gate.process_batch(batch)
        has_dropout = any(i.issue_type == "dropout" for i in result.quality_issues)
        has_gap = any(i.issue_type == "gap_beyond_bound" for i in result.quality_issues)
        assert has_dropout or has_gap
        assert result.overall_status in ("degraded", "quarantined")


@pytest.mark.unit
class TestQualityGateBoundsAndDrift:
    def test_implausible_value_quarantined(self) -> None:
        gate = DataQualityGate()
        batch = make_batch("implausible_value.csv")
        result = gate.process_batch(batch)
        implausible_issues = [
            i for i in result.quality_issues if i.issue_type == "implausible_value"
        ]
        assert len(implausible_issues) > 0
        assert result.quarantined_count > 0
        assert result.overall_status in ("degraded", "quarantined")

    def test_schema_drift_degraded_with_notice(self) -> None:
        gate = DataQualityGate()
        batch = make_batch("schema_drift.csv")
        result = gate.process_batch(batch)
        drift_issues = [i for i in result.quality_issues if i.issue_type == "schema_drift"]
        assert len(drift_issues) > 0
        assert result.overall_status in ("degraded", "quarantined")


@pytest.mark.unit
class TestBatchStatusLogic:
    def test_all_quarantined_batch_status(self) -> None:
        config = DataQualityGateConfig()
        config.bounds.circuit_type_bounds["hvac"].max_kwh = 0.001
        config.bounds.circuit_type_bounds["lighting"].max_kwh = 0.001
        config.bounds.default_bounds.max_kwh = 0.001
        gate_strict = DataQualityGate(config)
        batch = make_batch("clean_batch.csv")
        result = gate_strict.process_batch(batch)
        assert result.overall_status == "quarantined"
