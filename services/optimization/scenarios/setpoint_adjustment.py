"""ENG-4b — setpoint_adjustment_v1: HVAC setpoint relaxation.

TRD v2.0 §4: "Heuristic + LP (HVAC setpoint delta vs. ASHRAE-referenced
consumption-per-degree factor)."

Heuristic: OptimizationSettings.consumption_per_degree_c_fraction, a
PROPOSED (not yet ratified) fraction-of-HVAC-load reduction per degree C of
setpoint relaxation -- flagged for confirmation against an ASHRAE guideline
citation before production deployment (see shared/config/optimization.py).

LP: choose the setpoint delta (bounded by max_setpoint_delta_c) that
maximizes the heuristic's reduction. Linear in delta, so scipy.optimize
drives delta to its upper bound -- the LP formulation exists so the bound
itself (not just the heuristic factor) is the single point of control for
how aggressive a recommendation this scenario ever produces.

Justification: fires only for a finding on an HVAC circuit
(submeter_circuits.circuit_type == 'hvac') -- setpoint relaxation is
meaningless for a non-HVAC load.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from scipy.optimize import linprog

from services.optimization.interfaces import JustifyingFinding, OptimizationContext
from services.optimization.models import OptimizationScenario, ScenarioUnavailable
from services.optimization.tariff import blended_tariff_rate


class SetpointAdjustmentV1:
    name = "setpoint_adjustment_v1"
    version = 1

    def generate(self, context: OptimizationContext) -> OptimizationScenario | ScenarioUnavailable:
        hvac_circuit_ids = {c.circuit_id for c in context.circuits if c.circuit_type == "hvac"}
        finding = _find_hvac_finding(context.justifying_findings, hvac_circuit_ids)
        if finding is None:
            return ScenarioUnavailable(
                scenario_model=self.name,
                model_version=self.version,
                building_id=context.building_id,
                reason="No open/confirmed finding cites an HVAC circuit for this building.",
            )

        assert finding.circuit_id is not None  # guaranteed by _find_hvac_finding
        readings = context.readings_by_circuit.get(finding.circuit_id, [])
        if not readings:
            return ScenarioUnavailable(
                scenario_model=self.name,
                model_version=self.version,
                building_id=context.building_id,
                reason=(
                    f"Justifying finding {finding.finding_id} cites HVAC circuit "
                    f"{finding.circuit_id}, but no normalized_readings were found "
                    "for it in the lookback window."
                ),
            )

        settings = context.settings
        baseline_kwh = sum(r.kwh for r in readings if r.kwh is not None)
        if baseline_kwh <= 0:
            return ScenarioUnavailable(
                scenario_model=self.name,
                model_version=self.version,
                building_id=context.building_id,
                reason="No positive HVAC consumption found in the lookback window.",
            )

        # maximize delta (more setpoint relaxation -> more reduction, per the
        # heuristic factor) subject to the configured plausibility ceiling.
        # linprog minimizes, so c = [-1] drives delta to its upper bound.
        result = linprog(
            c=[-1.0],
            bounds=[(0.0, settings.max_setpoint_delta_c)],
            method="highs",
        )
        delta_c = float(result.x[0]) if result.success else 0.0

        reduction_fraction = min(settings.consumption_per_degree_c_fraction * delta_c, 1.0)
        optimized_kwh = baseline_kwh * (1.0 - reduction_fraction)
        pct_reduction = reduction_fraction * 100.0

        carbon_intensity = context.carbon_intensity_kg_per_kwh
        baseline_emissions = baseline_kwh * carbon_intensity
        optimized_emissions = optimized_kwh * carbon_intensity

        blended_rate = blended_tariff_rate(context, readings)
        annualization = 365.0 / max(settings.window_days, 1)
        annual_savings_inr = (baseline_kwh - optimized_kwh) * blended_rate * annualization

        return OptimizationScenario(
            scenario_id=uuid4(),
            scenario_model=self.name,
            model_version=self.version,
            building_id=context.building_id,
            justifying_finding_ids=[finding.finding_id],
            baseline_kwh=round(baseline_kwh, 2),
            optimized_kwh=round(optimized_kwh, 2),
            baseline_emissions_kg_co2=round(baseline_emissions, 2),
            optimized_emissions_kg_co2=round(optimized_emissions, 2),
            pct_reduction=round(pct_reduction, 2),
            confidence_band={
                "lower_pct": round(pct_reduction * 0.6, 2),
                "upper_pct": round(min(pct_reduction * 1.4, 100.0), 2),
            },
            estimated_annual_savings_inr=round(annual_savings_inr, 2),
            payback_months=0.0,
        )


def _find_hvac_finding(
    findings: list[JustifyingFinding], hvac_circuit_ids: set[UUID]
) -> JustifyingFinding | None:
    for finding in findings:
        if finding.circuit_id is not None and finding.circuit_id in hvac_circuit_ids:
            return finding
    return None
