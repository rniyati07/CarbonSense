from __future__ import annotations

from services.optimization.interfaces import JustifyingFinding
from services.optimization.models import OptimizationScenario, ScenarioUnavailable
from services.optimization.scenarios.solar_offset import SolarOffsetV1

from .conftest import CIRCUIT_ID, make_context, make_readings


class TestSolarOffsetV1:
    def test_no_findings_is_unavailable(self) -> None:
        context = make_context(
            justifying_findings=[],
            declared_rooftop_area_sqm=500.0,
            latitude=12.97,
            longitude=77.59,
            solar_irradiance_kwh_per_sqm_day=5.6,
            readings_by_circuit={CIRCUIT_ID: make_readings()},
        )
        result = SolarOffsetV1().generate(context)
        assert isinstance(result, ScenarioUnavailable)
        assert "finding" in result.reason.lower()

    def test_no_declared_rooftop_area_is_unavailable(self, hvac_finding: JustifyingFinding) -> None:
        context = make_context(
            justifying_findings=[hvac_finding],
            declared_rooftop_area_sqm=None,
            latitude=12.97,
            longitude=77.59,
            solar_irradiance_kwh_per_sqm_day=5.6,
            readings_by_circuit={CIRCUIT_ID: make_readings()},
        )
        result = SolarOffsetV1().generate(context)
        assert isinstance(result, ScenarioUnavailable)
        assert "rooftop" in result.reason.lower()

    def test_no_location_is_unavailable(self, hvac_finding: JustifyingFinding) -> None:
        context = make_context(
            justifying_findings=[hvac_finding],
            declared_rooftop_area_sqm=500.0,
            latitude=None,
            longitude=None,
            solar_irradiance_kwh_per_sqm_day=None,
            readings_by_circuit={CIRCUIT_ID: make_readings()},
        )
        result = SolarOffsetV1().generate(context)
        assert isinstance(result, ScenarioUnavailable)
        assert "location" in result.reason.lower()

    def test_no_irradiance_data_is_unavailable(self, hvac_finding: JustifyingFinding) -> None:
        context = make_context(
            justifying_findings=[hvac_finding],
            declared_rooftop_area_sqm=500.0,
            latitude=12.97,
            longitude=77.59,
            solar_irradiance_kwh_per_sqm_day=None,
            readings_by_circuit={CIRCUIT_ID: make_readings()},
        )
        result = SolarOffsetV1().generate(context)
        assert isinstance(result, ScenarioUnavailable)
        assert "irradiance" in result.reason.lower()

    def test_produces_a_valid_scenario_with_small_rooftop(
        self, hvac_finding: JustifyingFinding
    ) -> None:
        """A small, realistic rooftop relative to consumption -- avoids the
        absurd-oversizing case that legitimately fails bounds (covered by
        test_service.py's bounds-rejection test)."""
        context = make_context(
            justifying_findings=[hvac_finding],
            declared_rooftop_area_sqm=5.0,
            latitude=12.97,
            longitude=77.59,
            solar_irradiance_kwh_per_sqm_day=5.6,
            readings_by_circuit={CIRCUIT_ID: make_readings()},
        )
        result = SolarOffsetV1().generate(context)
        assert isinstance(result, OptimizationScenario)
        assert result.scenario_model == "solar_offset_v1"
        assert set(result.justifying_finding_ids) == {hvac_finding.finding_id}
        assert result.optimized_kwh < result.baseline_kwh
        assert result.payback_months > 0.0
