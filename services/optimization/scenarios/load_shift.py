"""ENG-4b — load_shift_v1: time-of-use tariff arbitrage on peak-hour load.

TRD v2.0 §4: "LP (time-of-use tariff arbitrage on peak-hour load identified
by justifying findings)."

Justification: fires only when a finding cites one of the rule engine's
load-timing rules (hvac_after_hours_v3, weekend_vampire_load_v1,
scheduling_violation_v1) -- every currently-shipped domain rule is, in fact,
a load-timing rule (services/rules_engine/rules/), so this is the load-shift
scenario's complete justification set today; a future rule that flags
timing-unrelated waste should not be added here.

Interpretation note (baseline_kwh/optimized_kwh): these track the
circuit's PEAK-HOUR kWh specifically, not whole-building kWh -- "shifting"
peak-hour load to off-peak hours conserves total energy (and therefore total
emissions, under this scenario's constant-carbon-intensity simplification;
see module docstring in bounds.py) but genuinely reduces the peak-hour
figure the LP optimizes against, matching TRD's own worked example
(18400 -> 15200, a real reduction in the tracked metric).
"""

from __future__ import annotations

from uuid import uuid4

from scipy.optimize import linprog

from services.optimization.interfaces import JustifyingFinding, OptimizationContext
from services.optimization.models import OptimizationScenario, ScenarioUnavailable
from services.optimization.tariff import peak_and_offpeak_rates

_JUSTIFYING_RULE_IDS = frozenset(
    {"hvac_after_hours_v3", "weekend_vampire_load_v1", "scheduling_violation_v1"}
)


class LoadShiftV1:
    name = "load_shift_v1"
    version = 1

    def generate(self, context: OptimizationContext) -> OptimizationScenario | ScenarioUnavailable:
        finding = _find_justifying_finding(context.justifying_findings)
        if finding is None:
            return ScenarioUnavailable(
                scenario_model=self.name,
                model_version=self.version,
                building_id=context.building_id,
                reason=(
                    "No open/confirmed finding cites a load-timing rule "
                    f"({sorted(_JUSTIFYING_RULE_IDS)}) for this building."
                ),
            )

        readings = (
            context.readings_by_circuit.get(finding.circuit_id, []) if finding.circuit_id else []
        )
        if not readings:
            return ScenarioUnavailable(
                scenario_model=self.name,
                model_version=self.version,
                building_id=context.building_id,
                reason=(
                    f"Justifying finding {finding.finding_id} cites circuit "
                    f"{finding.circuit_id}, but no normalized_readings were found "
                    "for it in the lookback window."
                ),
            )

        settings = context.settings
        peak_hours = set(settings.default_peak_hours)
        peak_kwh = sum(r.kwh for r in readings if r.kwh is not None and r.ts.hour in peak_hours)

        if peak_kwh <= 0:
            return ScenarioUnavailable(
                scenario_model=self.name,
                model_version=self.version,
                building_id=context.building_id,
                reason="No peak-hour consumption found for the justifying circuit.",
            )

        max_shift = peak_kwh * settings.max_shiftable_load_fraction
        peak_rate, offpeak_rate = peak_and_offpeak_rates(context)

        # minimize cost(x) = (peak_kwh - x) * peak_rate + (offpeak_kwh + x) * offpeak_rate
        #   = const + x * (offpeak_rate - peak_rate)
        # so c = [offpeak_rate - peak_rate]; since offpeak_rate < peak_rate this is
        # negative, and linprog (a minimizer) drives x to its upper bound.
        c = [offpeak_rate - peak_rate]
        bounds = [(0.0, max_shift)]
        result = linprog(c, bounds=bounds, method="highs")
        shifted_kwh = float(result.x[0]) if result.success else 0.0

        baseline_kwh = peak_kwh
        optimized_kwh = peak_kwh - shifted_kwh
        pct_reduction = (shifted_kwh / peak_kwh) * 100.0 if peak_kwh > 0 else 0.0

        carbon_intensity = context.carbon_intensity_kg_per_kwh
        baseline_emissions = baseline_kwh * carbon_intensity
        optimized_emissions = optimized_kwh * carbon_intensity

        annualization = 365.0 / max(settings.window_days, 1)
        baseline_cost = peak_kwh * peak_rate
        optimized_cost = optimized_kwh * peak_rate + shifted_kwh * offpeak_rate
        annual_savings_inr = max(baseline_cost - optimized_cost, 0.0) * annualization

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
                "lower_pct": round(pct_reduction * 0.7, 2),
                "upper_pct": round(min(pct_reduction * 1.3, 100.0), 2),
            },
            estimated_annual_savings_inr=round(annual_savings_inr, 2),
            payback_months=0.0,
        )


def _find_justifying_finding(findings: list[JustifyingFinding]) -> JustifyingFinding | None:
    for finding in findings:
        if _JUSTIFYING_RULE_IDS.intersection(finding.rule_ids):
            return finding
    return None
