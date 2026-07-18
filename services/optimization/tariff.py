"""ENG-4b — shared tariff-rate helpers.

Both setpoint_adjustment_v1 and solar_offset_v1 need a single blended
peak/off-peak rate for a set of readings that span both buckets (unlike
load_shift_v1, which deals with the peak-hour and off-peak buckets
separately by construction). Factored out here so the two scenario models
don't maintain independent copies of the same time-weighting logic.
"""

from __future__ import annotations

from services.ingestion.models import NormalizedReading
from services.optimization.interfaces import OptimizationContext


def peak_and_offpeak_rates(context: OptimizationContext) -> tuple[float, float]:
    """Resolve (peak_rate, offpeak_rate) from the building's declared
    tariff schedule, falling back to OptimizationSettings' static default
    per rate when the schedule is absent or missing a key."""
    settings = context.settings
    schedule = context.declared_tariff_schedule
    peak_rate = settings.default_peak_rate_inr_per_kwh
    offpeak_rate = settings.default_offpeak_rate_inr_per_kwh
    if schedule:
        peak_raw = schedule.get("peak_rate_inr_per_kwh")
        offpeak_raw = schedule.get("offpeak_rate_inr_per_kwh")
        if isinstance(peak_raw, (int, float)):
            peak_rate = float(peak_raw)
        if isinstance(offpeak_raw, (int, float)):
            offpeak_rate = float(offpeak_raw)
    return peak_rate, offpeak_rate


def blended_tariff_rate(context: OptimizationContext, readings: list[NormalizedReading]) -> float:
    """Time-weighted average of peak/off-peak rates across *readings*'
    actual hour-of-day distribution."""
    peak_rate, offpeak_rate = peak_and_offpeak_rates(context)
    peak_hours = set(context.settings.default_peak_hours)
    peak_kwh = sum(r.kwh for r in readings if r.kwh is not None and r.ts.hour in peak_hours)
    total_kwh = sum(r.kwh for r in readings if r.kwh is not None)
    if total_kwh <= 0:
        return offpeak_rate
    peak_share = peak_kwh / total_kwh
    return peak_share * peak_rate + (1.0 - peak_share) * offpeak_rate
