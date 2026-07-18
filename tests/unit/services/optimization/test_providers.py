from __future__ import annotations

import datetime

from services.optimization.interfaces import CarbonIntensityProvider, SolarProvider
from services.optimization.providers import StaticCarbonIntensityProvider, StaticSolarProvider
from shared.config.optimization import OptimizationSettings


class TestStaticSolarProvider:
    def test_satisfies_solar_provider_protocol(self) -> None:
        assert isinstance(StaticSolarProvider(), SolarProvider)

    def test_returns_a_band_value_for_southern_india(self) -> None:
        irradiance = StaticSolarProvider().get_irradiance(12.97, 77.59)
        assert irradiance is not None
        assert irradiance > 0

    def test_returns_a_lower_band_value_for_northern_latitude(self) -> None:
        south = StaticSolarProvider().get_irradiance(12.97, 77.59)
        north = StaticSolarProvider().get_irradiance(28.6, 77.2)
        assert north is not None and south is not None
        assert north <= south

    def test_returns_none_outside_valid_latitude_longitude_range(self) -> None:
        assert StaticSolarProvider().get_irradiance(999.0, 0.0) is None
        assert StaticSolarProvider().get_irradiance(0.0, 999.0) is None

    def test_handles_negative_latitude(self) -> None:
        assert StaticSolarProvider().get_irradiance(-12.0, 77.0) is not None


class TestStaticCarbonIntensityProvider:
    def test_satisfies_carbon_intensity_provider_protocol(self) -> None:
        assert isinstance(StaticCarbonIntensityProvider(), CarbonIntensityProvider)

    def test_returns_settings_default(self) -> None:
        settings = OptimizationSettings(default_grid_carbon_intensity_kg_per_kwh=0.5)
        provider = StaticCarbonIntensityProvider(settings)
        result = provider.get_intensity(None, datetime.datetime.now(datetime.UTC))
        assert result == 0.5

    def test_ignores_climate_zone_and_time(self) -> None:
        provider = StaticCarbonIntensityProvider()
        a = provider.get_intensity("deccan", datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC))
        b = provider.get_intensity(None, datetime.datetime(2027, 6, 1, tzinfo=datetime.UTC))
        assert a == b
