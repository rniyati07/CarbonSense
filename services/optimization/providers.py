"""ENG-4 — Solar and Carbon Intensity provider implementations.

Both default implementations here are static/heuristic, PROPOSED (not yet
validated against a real vendor) -- the same interim-adapter pattern already
accepted in this codebase for LocalModelRegistry (models/serving/
local_registry.py), which stands in for the not-yet-built MLflow model
registry behind the identical ModelRegistryProtocol.  The Protocol boundary
(interfaces.py) is what "no vendor lock-in" actually requires: swapping in a
real Solar/Carbon Intensity API later is a pure dependency-injection change,
nothing in services/optimization/scenarios/ needs to change.

To add a real provider (e.g. Open-Meteo, NREL, a commercial grid-intensity
API): implement SolarProvider/CarbonIntensityProvider and inject it into
OptimizationService in place of the Static* default.
"""

from __future__ import annotations

import datetime

from shared.config.optimization import OptimizationSettings

# PROPOSED: coarse latitude-band average daily irradiance (kWh/m^2/day),
# India-representative (PRD/TRD scope: INR-denominated, Indian commercial
# buildings). EMPIRICAL VALIDATION REQUIRED against a real solar-resource
# provider before production deployment.
_LATITUDE_BAND_IRRADIANCE_KWH_PER_SQM_DAY: tuple[tuple[float, float], ...] = (
    # (latitude upper bound, kWh/m^2/day)
    (15.0, 5.6),  # far south (e.g. Kerala, Tamil Nadu)
    (23.0, 5.2),  # central/deccan (e.g. Karnataka, Telangana, Maharashtra)
    (30.0, 4.8),  # north-central (e.g. Delhi NCR, UP)
    (90.0, 4.2),  # far north (e.g. Himalayan region)
)


class StaticSolarProvider:
    """Coarse latitude-band irradiance lookup -- no external API call.

    Returns None outside a plausible latitude range (mirrors a real
    provider's "outside coverage" response) so solar_offset_v1's
    applicability gate behaves identically once a real provider is
    swapped in.
    """

    def get_irradiance(self, latitude: float, longitude: float) -> float | None:
        if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
            return None
        abs_lat = abs(latitude)
        for upper_bound, irradiance in _LATITUDE_BAND_IRRADIANCE_KWH_PER_SQM_DAY:
            if abs_lat <= upper_bound:
                return irradiance
        return None


class StaticCarbonIntensityProvider:
    """Returns OptimizationSettings.default_grid_carbon_intensity_kg_per_kwh
    regardless of region/time -- no time-of-day or regional grid-mix
    modeling until a real Carbon Intensity Provider is wired in.
    """

    def __init__(self, settings: OptimizationSettings | None = None) -> None:
        self._settings = settings or OptimizationSettings()

    def get_intensity(self, climate_zone: str | None, ts: datetime.datetime) -> float:
        return self._settings.default_grid_carbon_intensity_kg_per_kwh
