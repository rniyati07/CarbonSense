"""ENG-4a — OptimizationService: the single entry point callable from both
the API and Temporal with identical business logic (TRD v2.0 §4's
"Service boundary").

No Temporal or FastAPI import anywhere in this module -- callers (a plain
API handler, once ENG-5 exists, or orchestration/temporal/activities/
optimization.py, already built) construct an OptimizationService with a
tenant-scoped repository/registry/providers and call generate_scenarios()/
generate_portfolio() directly. The service has no framework coupling to
strip out later.
"""

from __future__ import annotations

import datetime
import logging
from uuid import UUID, uuid4

from services.optimization.bounds import validate_scenario
from services.optimization.interfaces import (
    CarbonIntensityProvider,
    OptimizationContext,
    SolarProvider,
)
from services.optimization.models import (
    ModelQualityIncident,
    OptimizationScenario,
    PortfolioOptimizationResult,
    PortfolioScenarioRollup,
    ScenarioOutcome,
    ScenarioUnavailable,
)
from services.optimization.registry import ScenarioRegistry
from services.optimization.repository import OptimizationRepository
from shared.config.optimization import OptimizationSettings

logger = logging.getLogger(__name__)


class BuildingNotFoundError(Exception):
    pass


class OptimizationService:
    def __init__(
        self,
        repository: OptimizationRepository,
        registry: ScenarioRegistry,
        solar_provider: SolarProvider,
        carbon_provider: CarbonIntensityProvider,
        settings: OptimizationSettings | None = None,
    ) -> None:
        self._repository = repository
        self._registry = registry
        self._solar_provider = solar_provider
        self._carbon_provider = carbon_provider
        self._settings = settings or OptimizationSettings()

    async def generate_scenarios(self, tenant_id: UUID, building_id: UUID) -> list[ScenarioOutcome]:
        """ENG-4a/4b/4c/4d: run every registered scenario model for one
        building. Every OptimizationScenario returned has already passed
        ENG-4d's bounds check; a model whose output fails bounds is
        rejected and replaced with ScenarioUnavailable, and an incident is
        persisted -- never returned as a (possibly clipped) scenario."""
        context = await self._build_context(tenant_id, building_id)

        outcomes: list[ScenarioOutcome] = []
        for model in self._registry.get_all():
            outcome = model.generate(context)
            if isinstance(outcome, OptimizationScenario):
                outcome = await self._enforce_bounds(tenant_id, outcome)
            outcomes.append(outcome)
        return outcomes

    async def generate_portfolio(
        self, tenant_id: UUID, building_ids: list[UUID]
    ) -> PortfolioOptimizationResult:
        """ENG-4e: aggregate per-building optimization across multiple
        buildings. Pure rollup over independently-computed
        generate_scenarios() calls -- no separate portfolio-level LP or
        algorithm."""
        per_building: dict[UUID, list[ScenarioOutcome]] = {}
        for building_id in building_ids:
            per_building[building_id] = await self.generate_scenarios(tenant_id, building_id)

        rollups: list[PortfolioScenarioRollup] = []
        for model in self._registry.get_all():
            contributing: list[tuple[UUID, OptimizationScenario]] = [
                (building_id, outcome)
                for building_id, outcomes in per_building.items()
                for outcome in outcomes
                if isinstance(outcome, OptimizationScenario)
                and outcome.scenario_model == model.name
            ]
            if not contributing:
                continue

            total_baseline_kwh = sum(o.baseline_kwh for _, o in contributing)
            total_optimized_kwh = sum(o.optimized_kwh for _, o in contributing)
            total_baseline_emissions = sum(o.baseline_emissions_kg_co2 for _, o in contributing)
            total_optimized_emissions = sum(o.optimized_emissions_kg_co2 for _, o in contributing)
            total_savings = sum(o.estimated_annual_savings_inr for _, o in contributing)
            pct_reduction = (
                ((total_baseline_kwh - total_optimized_kwh) / total_baseline_kwh) * 100.0
                if total_baseline_kwh > 0
                else 0.0
            )

            rollups.append(
                PortfolioScenarioRollup(
                    scenario_model=model.name,
                    model_version=model.version,
                    contributing_building_ids=[bid for bid, _ in contributing],
                    total_baseline_kwh=round(total_baseline_kwh, 2),
                    total_optimized_kwh=round(total_optimized_kwh, 2),
                    total_baseline_emissions_kg_co2=round(total_baseline_emissions, 2),
                    total_optimized_emissions_kg_co2=round(total_optimized_emissions, 2),
                    pct_reduction=round(pct_reduction, 2),
                    total_estimated_annual_savings_inr=round(total_savings, 2),
                )
            )

        return PortfolioOptimizationResult(
            building_ids=building_ids,
            per_building=per_building,
            rollups=rollups,
        )

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #

    async def _build_context(self, tenant_id: UUID, building_id: UUID) -> OptimizationContext:
        building = await self._repository.get_building(building_id)
        if building is None:
            raise BuildingNotFoundError(f"Building {building_id} not found.")

        circuits = await self._repository.get_circuits(building_id)
        justifying_findings = await self._repository.get_justifying_findings(building_id)

        window_end = datetime.datetime.now(datetime.UTC)
        window_start = window_end - datetime.timedelta(days=self._settings.window_days)
        readings_by_circuit = await self._repository.get_readings_by_circuit(
            building_id, window_start, window_end
        )

        carbon_intensity = self._carbon_provider.get_intensity(building.climate_zone, window_end)

        solar_irradiance: float | None = None
        if building.latitude is not None and building.longitude is not None:
            solar_irradiance = self._solar_provider.get_irradiance(
                building.latitude, building.longitude
            )

        return OptimizationContext(
            tenant_id=tenant_id,
            building_id=building_id,
            building_type=building.building_type,
            climate_zone=building.climate_zone,
            declared_tariff_schedule=building.declared_tariff_schedule,
            declared_rooftop_area_sqm=building.declared_rooftop_area_sqm,
            latitude=building.latitude,
            longitude=building.longitude,
            justifying_findings=justifying_findings,
            circuits=circuits,
            readings_by_circuit=readings_by_circuit,
            carbon_intensity_kg_per_kwh=carbon_intensity,
            solar_irradiance_kwh_per_sqm_day=solar_irradiance,
            settings=self._settings,
        )

    async def _enforce_bounds(
        self, tenant_id: UUID, scenario: OptimizationScenario
    ) -> ScenarioOutcome:
        violations = validate_scenario(scenario, self._settings)
        if not violations:
            return scenario

        message = "; ".join(v.message for v in violations)
        logger.warning(
            "Scenario %s for building=%s failed bounds check: %s",
            scenario.scenario_model,
            scenario.building_id,
            message,
        )
        incident = ModelQualityIncident(
            incident_id=uuid4(),
            tenant_id=tenant_id,
            building_id=scenario.building_id,
            scenario_model=scenario.scenario_model,
            incident_type=violations[0].incident_type,
            severity="warning",
            message=message,
            metadata={"violation_types": [v.incident_type for v in violations]},
            created_at=datetime.datetime.now(datetime.UTC),
        )
        await self._repository.save_incident(incident)

        return ScenarioUnavailable(
            scenario_model=scenario.scenario_model,
            model_version=scenario.model_version,
            building_id=scenario.building_id,
            reason=f"Rejected at the service layer (bounds check failed): {message}",
        )
