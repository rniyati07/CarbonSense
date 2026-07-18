from __future__ import annotations

from uuid import uuid4

from services.optimization.interfaces import JustifyingFinding
from services.optimization.models import OptimizationScenario, ScenarioUnavailable
from services.optimization.scenarios.load_shift import LoadShiftV1
from shared.config.optimization import OptimizationSettings

from .conftest import CIRCUIT_ID, make_context, make_readings


class TestLoadShiftV1:
    def test_no_justifying_finding_is_unavailable(self) -> None:
        unrelated_finding = JustifyingFinding(
            finding_id=uuid4(),
            circuit_id=CIRCUIT_ID,
            layer_origin="ml_ensemble",
            rule_ids=(),
            confidence=0.5,
        )
        context = make_context(
            justifying_findings=[unrelated_finding],
            readings_by_circuit={CIRCUIT_ID: make_readings()},
        )
        result = LoadShiftV1().generate(context)
        assert isinstance(result, ScenarioUnavailable)
        assert "load-timing rule" in result.reason

    def test_no_readings_for_circuit_is_unavailable(self, hvac_finding: JustifyingFinding) -> None:
        context = make_context(justifying_findings=[hvac_finding], readings_by_circuit={})
        result = LoadShiftV1().generate(context)
        assert isinstance(result, ScenarioUnavailable)
        assert "no normalized_readings" in result.reason.lower()

    def test_produces_a_valid_scenario_with_real_finding_and_readings(
        self, hvac_finding: JustifyingFinding
    ) -> None:
        context = make_context(
            justifying_findings=[hvac_finding],
            readings_by_circuit={CIRCUIT_ID: make_readings()},
        )
        result = LoadShiftV1().generate(context)
        assert isinstance(result, OptimizationScenario)
        assert result.scenario_model == "load_shift_v1"
        assert result.model_version == 1
        assert result.justifying_finding_ids == [hvac_finding.finding_id]
        assert result.payback_months == 0.0
        assert 0.0 < result.pct_reduction <= 100.0
        assert result.optimized_kwh < result.baseline_kwh

    def test_shift_is_bounded_by_max_shiftable_load_fraction(
        self, hvac_finding: JustifyingFinding
    ) -> None:
        settings = OptimizationSettings(max_shiftable_load_fraction=0.25)
        context = make_context(
            justifying_findings=[hvac_finding],
            readings_by_circuit={CIRCUIT_ID: make_readings()},
            settings=settings,
        )
        result = LoadShiftV1().generate(context)
        assert isinstance(result, OptimizationScenario)
        assert result.pct_reduction == 25.0

    def test_uses_declared_tariff_schedule_when_present(
        self, hvac_finding: JustifyingFinding
    ) -> None:
        context_default = make_context(
            justifying_findings=[hvac_finding],
            readings_by_circuit={CIRCUIT_ID: make_readings()},
        )
        context_custom = make_context(
            justifying_findings=[hvac_finding],
            readings_by_circuit={CIRCUIT_ID: make_readings()},
            declared_tariff_schedule={
                "peak_rate_inr_per_kwh": 20.0,
                "offpeak_rate_inr_per_kwh": 2.0,
            },
        )
        default_result = LoadShiftV1().generate(context_default)
        custom_result = LoadShiftV1().generate(context_custom)
        assert isinstance(default_result, OptimizationScenario)
        assert isinstance(custom_result, OptimizationScenario)
        # A wider peak/off-peak spread must produce strictly larger savings
        # for the identical shifted kWh.
        assert (
            custom_result.estimated_annual_savings_inr > default_result.estimated_annual_savings_inr
        )
