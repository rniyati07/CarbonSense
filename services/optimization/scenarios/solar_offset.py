"""ENG-4b — solar_offset_v1: rooftop PV generation offset.

TRD v2.0 §4: "Irradiance-lookup-informed offset estimate, gated on building
having usable rooftop/location data." No LP here -- unlike load_shift_v1/
setpoint_adjustment_v1, TRD does not describe this scenario as an LP
problem; it is a direct estimate from declared rooftop area and a solar
irradiance lookup (via SolarProvider), matching the spec instead of forcing
an unneeded optimization formulation onto it.

Applicability gate (both required):
  1. The building has declared usable rooftop data (declared_rooftop_area_sqm
     > 0, latitude/longitude set) and SolarProvider returned a non-None
     irradiance for that location.
  2. ENG-4c's blanket justification requirement: at least one open/confirmed
     finding exists for the building. Unlike load_shift_v1/
     setpoint_adjustment_v1 (justified by a *specific* load-timing/HVAC
     finding), any finding demonstrates the building has real, evidenced
     consumption to offset -- solar generation isn't tied to a particular
     anomaly's root cause the way shifting or setpoint changes are.

Sizing/economics assumptions (panel efficiency, performance ratio, capacity
density, installed cost per kW) are all PROPOSED in
shared/config/optimization.py -- flagged for empirical validation, not
hardcoded here.
"""

from __future__ import annotations

from uuid import uuid4

from services.optimization.interfaces import OptimizationContext
from services.optimization.models import OptimizationScenario, ScenarioUnavailable
from services.optimization.tariff import blended_tariff_rate


class SolarOffsetV1:
    name = "solar_offset_v1"
    version = 1

    def generate(self, context: OptimizationContext) -> OptimizationScenario | ScenarioUnavailable:
        if not context.justifying_findings:
            return ScenarioUnavailable(
                scenario_model=self.name,
                model_version=self.version,
                building_id=context.building_id,
                reason="No open/confirmed finding exists for this building.",
            )

        if not (context.declared_rooftop_area_sqm and context.declared_rooftop_area_sqm > 0):
            return ScenarioUnavailable(
                scenario_model=self.name,
                model_version=self.version,
                building_id=context.building_id,
                reason="Building has no declared usable rooftop area.",
            )

        if context.latitude is None or context.longitude is None:
            return ScenarioUnavailable(
                scenario_model=self.name,
                model_version=self.version,
                building_id=context.building_id,
                reason="Building has no declared location (latitude/longitude).",
            )

        if context.solar_irradiance_kwh_per_sqm_day is None:
            return ScenarioUnavailable(
                scenario_model=self.name,
                model_version=self.version,
                building_id=context.building_id,
                reason="SolarProvider has no irradiance data for this building's location.",
            )

        all_readings = [r for readings in context.readings_by_circuit.values() for r in readings]
        window_kwh = sum(r.kwh for r in all_readings if r.kwh is not None)
        if window_kwh <= 0:
            return ScenarioUnavailable(
                scenario_model=self.name,
                model_version=self.version,
                building_id=context.building_id,
                reason="No positive building-wide consumption found in the lookback window.",
            )

        settings = context.settings
        annualization = 365.0 / max(settings.window_days, 1)
        annual_baseline_kwh = window_kwh * annualization

        daily_generation_kwh = (
            context.declared_rooftop_area_sqm
            * context.solar_irradiance_kwh_per_sqm_day
            * settings.solar_panel_efficiency
            * settings.solar_performance_ratio
        )
        annual_generation_kwh = daily_generation_kwh * 365.0
        annual_optimized_kwh = max(annual_baseline_kwh - annual_generation_kwh, 0.0)

        pct_reduction = ((annual_baseline_kwh - annual_optimized_kwh) / annual_baseline_kwh) * 100.0

        carbon_intensity = context.carbon_intensity_kg_per_kwh
        baseline_emissions = annual_baseline_kwh * carbon_intensity
        optimized_emissions = annual_optimized_kwh * carbon_intensity

        blended_rate = blended_tariff_rate(context, all_readings)
        annual_savings_inr = (annual_baseline_kwh - annual_optimized_kwh) * blended_rate

        installed_kw = (
            context.declared_rooftop_area_sqm * settings.solar_capacity_density_kw_per_sqm
        )
        capex_inr = installed_kw * settings.solar_capex_inr_per_kw
        payback_months = (
            (capex_inr / (annual_savings_inr / 12.0)) if annual_savings_inr > 0 else 9999.0
        )

        return OptimizationScenario(
            scenario_id=uuid4(),
            scenario_model=self.name,
            model_version=self.version,
            building_id=context.building_id,
            justifying_finding_ids=[f.finding_id for f in context.justifying_findings],
            baseline_kwh=round(annual_baseline_kwh, 2),
            optimized_kwh=round(annual_optimized_kwh, 2),
            baseline_emissions_kg_co2=round(baseline_emissions, 2),
            optimized_emissions_kg_co2=round(optimized_emissions, 2),
            pct_reduction=round(pct_reduction, 2),
            confidence_band={
                "lower_pct": round(pct_reduction * 0.75, 2),
                "upper_pct": round(min(pct_reduction * 1.25, 100.0), 2),
            },
            estimated_annual_savings_inr=round(annual_savings_inr, 2),
            payback_months=round(payback_months, 1),
        )
