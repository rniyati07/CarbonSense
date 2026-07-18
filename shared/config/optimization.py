from __future__ import annotations

from pydantic_settings import BaseSettings


class OptimizationSettings(BaseSettings):
    """Configuration for the Optimization Engine (ENG-4).

    All numeric thresholds MUST be sourced from this model -- matches the
    convention already established by MLEnsembleConfig/CalibrationSettings.
    """

    model_config = {"env_prefix": "OPTIMIZATION_"}

    # ------------------------------------------------------------------ #
    # Historical lookback window for baseline kWh computation
    # ------------------------------------------------------------------ #
    window_days: int = 30

    # ------------------------------------------------------------------ #
    # Declared tariff schedule fallback (TRD v2.0 §4, DATA_AND_MODEL_STRATEGY
    # §3.3's "declared tariff schedule").  buildings.declared_tariff_schedule
    # is nullable -- these are the static fallback rates used when a building
    # has not declared its own.
    # PROPOSED DEFAULT: representative Indian commercial peak/off-peak tariff.
    # EMPIRICAL VALIDATION REQUIRED against real utility bills (GTM-2b) before
    # production deployment.
    # ------------------------------------------------------------------ #
    default_peak_rate_inr_per_kwh: float = 9.5
    default_offpeak_rate_inr_per_kwh: float = 6.0
    default_peak_hours: tuple[int, ...] = (9, 10, 11, 12, 13, 14, 15, 16, 17, 18)

    # ------------------------------------------------------------------ #
    # Carbon intensity fallback (DATA_AND_MODEL_STRATEGY §3.6).
    # PROPOSED DEFAULT: representative Indian grid average.
    # EMPIRICAL VALIDATION REQUIRED against a real Carbon Intensity Provider.
    # ------------------------------------------------------------------ #
    default_grid_carbon_intensity_kg_per_kwh: float = 0.71

    # ------------------------------------------------------------------ #
    # load_shift_v1 LP bounds
    # PROPOSED: maximum fraction of a justified peak-hour finding's load that
    # can plausibly be shifted to off-peak hours in one scenario.
    # ------------------------------------------------------------------ #
    max_shiftable_load_fraction: float = 0.4

    # ------------------------------------------------------------------ #
    # setpoint_adjustment_v1 heuristic
    # PROPOSED: ASHRAE-referenced consumption-per-degree-C factor (fraction
    # of HVAC circuit load per degree of setpoint relaxation).
    # EMPIRICAL VALIDATION REQUIRED -- confirm with ASHRAE guideline citation
    # before production deployment.
    # ------------------------------------------------------------------ #
    consumption_per_degree_c_fraction: float = 0.03
    max_setpoint_delta_c: float = 2.0

    # ------------------------------------------------------------------ #
    # solar_offset_v1 rooftop PV sizing/economics
    # PROPOSED: standard rooftop-PV assumptions (panel efficiency, system
    # performance ratio/derate, installed-capacity density, and installed
    # cost per kW). EMPIRICAL VALIDATION REQUIRED against real quotes
    # (GTM-2b) before production deployment.
    # ------------------------------------------------------------------ #
    solar_panel_efficiency: float = 0.18
    solar_performance_ratio: float = 0.75
    solar_capacity_density_kw_per_sqm: float = 0.15
    solar_capex_inr_per_kw: float = 45000.0

    # ------------------------------------------------------------------ #
    # ENG-4d bounds enforcement (TRD v2.0 §4: "Savings estimates are clamped
    # to a physically plausible range ... an out-of-bounds result is
    # rejected at the service layer ... not silently clipped").
    # PROPOSED: plausible range for any scenario's pct_reduction/payback.
    # ------------------------------------------------------------------ #
    min_plausible_pct_reduction: float = 0.0
    max_plausible_pct_reduction: float = 60.0
    max_plausible_payback_months: float = 120.0
