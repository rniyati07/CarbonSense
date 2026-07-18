from __future__ import annotations

import datetime
from uuid import UUID, uuid4

import pytest

from services.ingestion.models import NormalizedReading
from services.optimization.interfaces import CircuitInfo, JustifyingFinding, OptimizationContext
from shared.config.optimization import OptimizationSettings

TENANT_ID = uuid4()
BUILDING_ID = uuid4()
CIRCUIT_ID = uuid4()
WINDOW_START = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)


def make_readings(
    circuit_id: UUID = CIRCUIT_ID,
    days: int = 7,
    peak_kwh: float = 5.0,
    offpeak_kwh: float = 1.0,
    peak_hours: tuple[int, ...] = (9, 10, 11, 12, 13, 14, 15, 16, 17, 18),
) -> list[NormalizedReading]:
    readings = []
    for day in range(days):
        for hour in range(24):
            ts = WINDOW_START + datetime.timedelta(days=day, hours=hour)
            kwh = peak_kwh if hour in peak_hours else offpeak_kwh
            readings.append(
                NormalizedReading(
                    tenant_id=TENANT_ID,
                    circuit_id=circuit_id,
                    ts=ts,
                    kwh=kwh,
                    source_system="test",
                    ingestion_timestamp=WINDOW_START,
                    normalization_version="v1",
                )
            )
    return readings


def make_context(
    *,
    justifying_findings: list[JustifyingFinding] | None = None,
    circuits: list[CircuitInfo] | None = None,
    readings_by_circuit: dict[UUID, list[NormalizedReading]] | None = None,
    declared_tariff_schedule: dict[str, object] | None = None,
    declared_rooftop_area_sqm: float | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    solar_irradiance_kwh_per_sqm_day: float | None = None,
    carbon_intensity_kg_per_kwh: float = 0.71,
    settings: OptimizationSettings | None = None,
) -> OptimizationContext:
    return OptimizationContext(
        tenant_id=TENANT_ID,
        building_id=BUILDING_ID,
        building_type="office",
        climate_zone=None,
        declared_tariff_schedule=declared_tariff_schedule,
        declared_rooftop_area_sqm=declared_rooftop_area_sqm,
        latitude=latitude,
        longitude=longitude,
        justifying_findings=justifying_findings or [],
        circuits=circuits or [],
        readings_by_circuit=readings_by_circuit or {},
        carbon_intensity_kg_per_kwh=carbon_intensity_kg_per_kwh,
        solar_irradiance_kwh_per_sqm_day=solar_irradiance_kwh_per_sqm_day,
        settings=settings or OptimizationSettings(),
    )


@pytest.fixture()
def fast_settings() -> OptimizationSettings:
    return OptimizationSettings()


@pytest.fixture()
def hvac_finding() -> JustifyingFinding:
    return JustifyingFinding(
        finding_id=uuid4(),
        circuit_id=CIRCUIT_ID,
        layer_origin="domain_rule",
        rule_ids=("hvac_after_hours_v3",),
        confidence=None,
    )


@pytest.fixture()
def hvac_circuit() -> CircuitInfo:
    return CircuitInfo(circuit_id=CIRCUIT_ID, circuit_type="hvac")
