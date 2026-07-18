from __future__ import annotations

from uuid import uuid4

from services.optimization.bounds import validate_scenario
from services.optimization.models import OptimizationScenario
from shared.config.optimization import OptimizationSettings


def _make_scenario(**overrides: object) -> OptimizationScenario:
    defaults: dict[str, object] = {
        "scenario_id": uuid4(),
        "scenario_model": "load_shift_v1",
        "model_version": 1,
        "building_id": uuid4(),
        "justifying_finding_ids": [uuid4()],
        "baseline_kwh": 100.0,
        "optimized_kwh": 80.0,
        "baseline_emissions_kg_co2": 71.0,
        "optimized_emissions_kg_co2": 56.8,
        "pct_reduction": 20.0,
        "confidence_band": {"lower_pct": 14.0, "upper_pct": 26.0},
        "estimated_annual_savings_inr": 5000.0,
        "payback_months": 0.0,
    }
    defaults.update(overrides)
    return OptimizationScenario(**defaults)


class TestValidateScenario:
    def test_passes_a_physically_consistent_scenario(self) -> None:
        scenario = _make_scenario()
        assert validate_scenario(scenario, OptimizationSettings()) == []

    def test_rejects_consumption_increase(self) -> None:
        scenario = _make_scenario(baseline_kwh=100.0, optimized_kwh=120.0, pct_reduction=0.0)
        violations = validate_scenario(scenario, OptimizationSettings())
        assert any(v.incident_type == "consumption_increase" for v in violations)

    def test_rejects_emissions_increase(self) -> None:
        scenario = _make_scenario(baseline_emissions_kg_co2=50.0, optimized_emissions_kg_co2=60.0)
        violations = validate_scenario(scenario, OptimizationSettings())
        assert any(v.incident_type == "emissions_increase" for v in violations)

    def test_rejects_pct_reduction_inconsistent_with_kwh(self) -> None:
        scenario = _make_scenario(baseline_kwh=100.0, optimized_kwh=80.0, pct_reduction=90.0)
        violations = validate_scenario(scenario, OptimizationSettings())
        assert any(v.incident_type == "pct_reduction_inconsistent" for v in violations)

    def test_rejects_pct_reduction_above_plausible_ceiling(self) -> None:
        settings = OptimizationSettings(max_plausible_pct_reduction=30.0)
        scenario = _make_scenario(baseline_kwh=100.0, optimized_kwh=40.0, pct_reduction=60.0)
        violations = validate_scenario(scenario, settings)
        assert any(v.incident_type == "pct_reduction_out_of_range" for v in violations)

    def test_rejects_implausible_payback(self) -> None:
        settings = OptimizationSettings(max_plausible_payback_months=24.0)
        scenario = _make_scenario(payback_months=200.0)
        violations = validate_scenario(scenario, settings)
        assert any(v.incident_type == "payback_implausible" for v in violations)

    def test_accumulates_multiple_violations(self) -> None:
        scenario = _make_scenario(
            baseline_kwh=100.0,
            optimized_kwh=120.0,
            baseline_emissions_kg_co2=50.0,
            optimized_emissions_kg_co2=60.0,
            pct_reduction=0.0,
        )
        violations = validate_scenario(scenario, OptimizationSettings())
        assert len(violations) >= 2
