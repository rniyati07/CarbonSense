from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from services.optimization.interfaces import OptimizationContext
from services.optimization.models import (
    ModelQualityIncident,
    OptimizationScenario,
    ScenarioUnavailable,
)
from services.optimization.registry import ScenarioRegistry
from services.optimization.repository import BuildingRecord
from services.optimization.service import BuildingNotFoundError, OptimizationService

TENANT_ID = uuid4()
BUILDING_ID = uuid4()


def _valid_scenario(**overrides: object) -> OptimizationScenario:
    defaults: dict[str, object] = {
        "scenario_id": uuid4(),
        "scenario_model": "fake_model_v1",
        "model_version": 1,
        "building_id": BUILDING_ID,
        "justifying_finding_ids": [uuid4()],
        "baseline_kwh": 100.0,
        "optimized_kwh": 80.0,
        "baseline_emissions_kg_co2": 71.0,
        "optimized_emissions_kg_co2": 56.8,
        "pct_reduction": 20.0,
        "confidence_band": {"lower_pct": 14.0, "upper_pct": 26.0},
        "estimated_annual_savings_inr": 5000.0,
        "payback_months": 0.0,
    }
    defaults.update(overrides)
    return OptimizationScenario(**defaults)


class _FakeModel:
    def __init__(self, name: str, outcome_factory) -> None:
        self.name = name
        self.version = 1
        self._outcome_factory = outcome_factory

    def generate(self, context: OptimizationContext) -> object:
        return self._outcome_factory(context)


@pytest.fixture()
def mock_repository() -> AsyncMock:
    repo = AsyncMock()
    repo.get_building.return_value = BuildingRecord(
        building_type="office",
        climate_zone=None,
        declared_tariff_schedule=None,
        declared_rooftop_area_sqm=None,
        latitude=None,
        longitude=None,
    )
    repo.get_circuits.return_value = []
    repo.get_justifying_findings.return_value = []
    repo.get_readings_by_circuit.return_value = {}
    return repo


@pytest.fixture()
def fake_solar_provider() -> object:
    class _Provider:
        def get_irradiance(self, latitude: float, longitude: float) -> float | None:
            return None

    return _Provider()


@pytest.fixture()
def fake_carbon_provider() -> object:
    class _Provider:
        def get_intensity(self, climate_zone: str | None, ts: object) -> float:
            return 0.71

    return _Provider()


class TestGenerateScenarios:
    @pytest.mark.asyncio
    async def test_building_not_found_raises(
        self, mock_repository: AsyncMock, fake_solar_provider: object, fake_carbon_provider: object
    ) -> None:
        mock_repository.get_building.return_value = None
        service = OptimizationService(
            repository=mock_repository,
            registry=ScenarioRegistry(),
            solar_provider=fake_solar_provider,
            carbon_provider=fake_carbon_provider,
        )
        with pytest.raises(BuildingNotFoundError):
            await service.generate_scenarios(TENANT_ID, BUILDING_ID)

    @pytest.mark.asyncio
    async def test_valid_scenario_passes_through(
        self, mock_repository: AsyncMock, fake_solar_provider: object, fake_carbon_provider: object
    ) -> None:
        registry = ScenarioRegistry()
        registry.register(_FakeModel("fake_model_v1", lambda ctx: _valid_scenario()))
        service = OptimizationService(
            repository=mock_repository,
            registry=registry,
            solar_provider=fake_solar_provider,
            carbon_provider=fake_carbon_provider,
        )
        outcomes = await service.generate_scenarios(TENANT_ID, BUILDING_ID)
        assert len(outcomes) == 1
        assert isinstance(outcomes[0], OptimizationScenario)
        mock_repository.save_incident.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unavailable_outcome_passes_through_unchanged(
        self, mock_repository: AsyncMock, fake_solar_provider: object, fake_carbon_provider: object
    ) -> None:
        unavailable = ScenarioUnavailable(
            scenario_model="fake_model_v1",
            model_version=1,
            building_id=BUILDING_ID,
            reason="no data",
        )
        registry = ScenarioRegistry()
        registry.register(_FakeModel("fake_model_v1", lambda ctx: unavailable))
        service = OptimizationService(
            repository=mock_repository,
            registry=registry,
            solar_provider=fake_solar_provider,
            carbon_provider=fake_carbon_provider,
        )
        outcomes = await service.generate_scenarios(TENANT_ID, BUILDING_ID)
        assert outcomes == [unavailable]
        mock_repository.save_incident.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_bounds_violation_is_rejected_and_incident_persisted(
        self, mock_repository: AsyncMock, fake_solar_provider: object, fake_carbon_provider: object
    ) -> None:
        # optimized_kwh > baseline_kwh -- a real, unambiguous bounds violation.
        invalid_scenario = _valid_scenario(
            baseline_kwh=100.0, optimized_kwh=150.0, pct_reduction=0.0
        )
        registry = ScenarioRegistry()
        registry.register(_FakeModel("fake_model_v1", lambda ctx: invalid_scenario))
        service = OptimizationService(
            repository=mock_repository,
            registry=registry,
            solar_provider=fake_solar_provider,
            carbon_provider=fake_carbon_provider,
        )
        outcomes = await service.generate_scenarios(TENANT_ID, BUILDING_ID)

        assert len(outcomes) == 1
        assert isinstance(outcomes[0], ScenarioUnavailable)
        assert "bounds check failed" in outcomes[0].reason.lower()

        mock_repository.save_incident.assert_awaited_once()
        incident = mock_repository.save_incident.call_args.args[0]
        assert isinstance(incident, ModelQualityIncident)
        assert incident.scenario_model == "fake_model_v1"
        assert incident.tenant_id == TENANT_ID
        assert incident.building_id == BUILDING_ID

    @pytest.mark.asyncio
    async def test_multiple_registered_models_all_run(
        self, mock_repository: AsyncMock, fake_solar_provider: object, fake_carbon_provider: object
    ) -> None:
        registry = ScenarioRegistry()
        registry.register(
            _FakeModel("model_a", lambda ctx: _valid_scenario(scenario_model="model_a"))
        )
        registry.register(
            _FakeModel(
                "model_b",
                lambda ctx: ScenarioUnavailable(
                    scenario_model="model_b", model_version=1, building_id=BUILDING_ID, reason="x"
                ),
            )
        )
        service = OptimizationService(
            repository=mock_repository,
            registry=registry,
            solar_provider=fake_solar_provider,
            carbon_provider=fake_carbon_provider,
        )
        outcomes = await service.generate_scenarios(TENANT_ID, BUILDING_ID)
        assert {o.scenario_model for o in outcomes} == {"model_a", "model_b"}


class TestGeneratePortfolio:
    @pytest.mark.asyncio
    async def test_aggregates_across_buildings(
        self, mock_repository: AsyncMock, fake_solar_provider: object, fake_carbon_provider: object
    ) -> None:
        building_a, building_b = uuid4(), uuid4()
        registry = ScenarioRegistry()
        registry.register(
            _FakeModel(
                "fake_model_v1",
                lambda ctx: _valid_scenario(
                    building_id=ctx.building_id, baseline_kwh=100.0, optimized_kwh=80.0
                ),
            )
        )
        service = OptimizationService(
            repository=mock_repository,
            registry=registry,
            solar_provider=fake_solar_provider,
            carbon_provider=fake_carbon_provider,
        )
        result = await service.generate_portfolio(TENANT_ID, [building_a, building_b])

        assert set(result.building_ids) == {building_a, building_b}
        assert len(result.per_building) == 2
        assert len(result.rollups) == 1
        rollup = result.rollups[0]
        assert rollup.scenario_model == "fake_model_v1"
        assert set(rollup.contributing_building_ids) == {building_a, building_b}
        assert rollup.total_baseline_kwh == 200.0
        assert rollup.total_optimized_kwh == 160.0
        assert rollup.pct_reduction == 20.0

    @pytest.mark.asyncio
    async def test_no_rollup_when_no_building_produces_a_valid_scenario(
        self, mock_repository: AsyncMock, fake_solar_provider: object, fake_carbon_provider: object
    ) -> None:
        registry = ScenarioRegistry()
        registry.register(
            _FakeModel(
                "fake_model_v1",
                lambda ctx: ScenarioUnavailable(
                    scenario_model="fake_model_v1",
                    model_version=1,
                    building_id=ctx.building_id,
                    reason="no data",
                ),
            )
        )
        service = OptimizationService(
            repository=mock_repository,
            registry=registry,
            solar_provider=fake_solar_provider,
            carbon_provider=fake_carbon_provider,
        )
        result = await service.generate_portfolio(TENANT_ID, [uuid4()])
        assert result.rollups == []
