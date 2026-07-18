from __future__ import annotations

from uuid import uuid4

from services.optimization.interfaces import CircuitInfo, JustifyingFinding
from services.optimization.models import OptimizationScenario, ScenarioUnavailable
from services.optimization.scenarios.setpoint_adjustment import SetpointAdjustmentV1
from shared.config.optimization import OptimizationSettings

from .conftest import CIRCUIT_ID, make_context, make_readings


class TestSetpointAdjustmentV1:
    def test_no_hvac_circuit_finding_is_unavailable(self) -> None:
        non_hvac_circuit = CircuitInfo(circuit_id=CIRCUIT_ID, circuit_type="lighting")
        finding = JustifyingFinding(
            finding_id=uuid4(),
            circuit_id=CIRCUIT_ID,
            layer_origin="domain_rule",
            rule_ids=("hvac_after_hours_v3",),
            confidence=None,
        )
        context = make_context(
            justifying_findings=[finding],
            circuits=[non_hvac_circuit],
            readings_by_circuit={CIRCUIT_ID: make_readings()},
        )
        result = SetpointAdjustmentV1().generate(context)
        assert isinstance(result, ScenarioUnavailable)
        assert "HVAC circuit" in result.reason

    def test_no_readings_is_unavailable(
        self, hvac_finding: JustifyingFinding, hvac_circuit: CircuitInfo
    ) -> None:
        context = make_context(
            justifying_findings=[hvac_finding], circuits=[hvac_circuit], readings_by_circuit={}
        )
        result = SetpointAdjustmentV1().generate(context)
        assert isinstance(result, ScenarioUnavailable)

    def test_produces_a_valid_scenario(
        self, hvac_finding: JustifyingFinding, hvac_circuit: CircuitInfo
    ) -> None:
        context = make_context(
            justifying_findings=[hvac_finding],
            circuits=[hvac_circuit],
            readings_by_circuit={CIRCUIT_ID: make_readings()},
        )
        result = SetpointAdjustmentV1().generate(context)
        assert isinstance(result, OptimizationScenario)
        assert result.scenario_model == "setpoint_adjustment_v1"
        assert result.justifying_finding_ids == [hvac_finding.finding_id]
        assert result.optimized_kwh < result.baseline_kwh
        assert result.payback_months == 0.0

    def test_reduction_scales_with_max_setpoint_delta(
        self, hvac_finding: JustifyingFinding, hvac_circuit: CircuitInfo
    ) -> None:
        readings = make_readings()
        small_delta = make_context(
            justifying_findings=[hvac_finding],
            circuits=[hvac_circuit],
            readings_by_circuit={CIRCUIT_ID: readings},
            settings=OptimizationSettings(max_setpoint_delta_c=1.0),
        )
        large_delta = make_context(
            justifying_findings=[hvac_finding],
            circuits=[hvac_circuit],
            readings_by_circuit={CIRCUIT_ID: readings},
            settings=OptimizationSettings(max_setpoint_delta_c=2.0),
        )
        small_result = SetpointAdjustmentV1().generate(small_delta)
        large_result = SetpointAdjustmentV1().generate(large_delta)
        assert isinstance(small_result, OptimizationScenario)
        assert isinstance(large_result, OptimizationScenario)
        assert large_result.pct_reduction > small_result.pct_reduction
