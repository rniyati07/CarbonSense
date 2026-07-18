"""ENG-4 — Optimization Engine interfaces.

ScenarioModel is the Protocol every scenario in services/optimization/scenarios/
implements; new scenarios register an instance with ScenarioRegistry (see
registry.py) rather than modifying OptimizationService's dispatch logic --
this is the extensibility point ENG-4b's "new scenarios should register, not
modify existing code" requirement is built around.

SolarProvider / CarbonIntensityProvider follow the identical abstract-
Protocol-plus-swappable-implementation pattern already established by
shared/calendar/holiday_provider.py's HolidayProvider -- source-agnostic per
DATA_AND_MODEL_STRATEGY §1, no vendor lock-in.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable
from uuid import UUID

from services.ingestion.models import NormalizedReading
from services.optimization.models import ScenarioOutcome
from shared.config.optimization import OptimizationSettings


@dataclass(frozen=True)
class JustifyingFinding:
    """The subset of a persisted Finding a scenario model needs to decide
    applicability and cite as justification (ENG-4c) -- not the full
    Finding/ExplainabilityBundle, which the repository layer already
    validated exists and is well-formed before constructing this."""

    finding_id: UUID
    circuit_id: UUID | None
    layer_origin: str
    rule_ids: tuple[str, ...]
    confidence: float | None


@dataclass(frozen=True)
class CircuitInfo:
    circuit_id: UUID
    circuit_type: str


@dataclass
class OptimizationContext:
    """Everything a ScenarioModel needs to decide applicability and, if
    applicable, compute a scenario -- assembled once per (tenant, building)
    by OptimizationService and handed to every registered scenario model."""

    tenant_id: UUID
    building_id: UUID
    building_type: str
    climate_zone: str | None
    declared_tariff_schedule: dict[str, object] | None
    declared_rooftop_area_sqm: float | None
    latitude: float | None
    longitude: float | None
    justifying_findings: list[JustifyingFinding]
    circuits: list[CircuitInfo]
    readings_by_circuit: dict[UUID, list[NormalizedReading]]
    carbon_intensity_kg_per_kwh: float
    solar_irradiance_kwh_per_sqm_day: float | None
    settings: OptimizationSettings = field(repr=False)


@runtime_checkable
class ScenarioModel(Protocol):
    """A single versioned scenario model (ENG-4b).

    `generate()` must never fabricate a scenario: if no justifying finding
    applies or a required precondition (e.g. declared rooftop data) is
    absent, return ScenarioUnavailable rather than a best-effort guess
    (ENG-4c).  Bounds enforcement (ENG-4d) happens once, centrally, in
    OptimizationService -- individual scenario models compute their best
    estimate; they do not clamp or self-censor.
    """

    name: str
    version: int

    def generate(self, context: OptimizationContext) -> ScenarioOutcome: ...


@runtime_checkable
class SolarProvider(Protocol):
    """Abstract interface for solar irradiance lookups (DATA_AND_MODEL_STRATEGY
    §3.4).  Swappable: configure via dependency injection, never hardcoded
    in scenario logic."""

    def get_irradiance(self, latitude: float, longitude: float) -> float | None:
        """Return average daily irradiance in kWh/m^2/day, or None if the
        location is outside the provider's coverage."""
        ...


@runtime_checkable
class CarbonIntensityProvider(Protocol):
    """Abstract interface for grid carbon-intensity lookups
    (DATA_AND_MODEL_STRATEGY §3.6).  Swappable: configure via dependency
    injection, never hardcoded in scenario logic."""

    def get_intensity(self, climate_zone: str | None, ts: datetime.datetime) -> float:
        """Return grid carbon intensity in kg CO2/kWh for the given
        region/time.  Must always return a value (fall back to a static
        default rather than None) -- every scenario needs an emissions
        figure to satisfy the TRD v2.0 §4 output contract."""
        ...
