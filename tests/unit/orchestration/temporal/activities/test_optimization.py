from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from orchestration.temporal.activities.optimization import optimization_activity
from orchestration.temporal.dto import AnalysisPipelineInput, ExplainabilityOutput
from services.optimization.models import OptimizationScenario, ScenarioUnavailable


def _patched_session():
    mock_session = AsyncMock()

    @asynccontextmanager
    async def fake_factory_cm():
        yield mock_session

    def fake_factory():
        return fake_factory_cm

    @asynccontextmanager
    async def fake_tenant_scope(session, tenant_id):
        yield session

    return (
        patch("shared.database.get_session_factory", fake_factory),
        patch("shared.auth.tenant_context.tenant_scope", fake_tenant_scope),
    )


def _make_scenario(building_id) -> OptimizationScenario:
    return OptimizationScenario(
        scenario_id=uuid4(),
        scenario_model="load_shift_v1",
        model_version=1,
        building_id=building_id,
        justifying_finding_ids=[uuid4()],
        baseline_kwh=100.0,
        optimized_kwh=80.0,
        baseline_emissions_kg_co2=71.0,
        optimized_emissions_kg_co2=56.8,
        pct_reduction=20.0,
        confidence_band={"lower_pct": 14.0, "upper_pct": 26.0},
        estimated_annual_savings_inr=5000.0,
        payback_months=0.0,
    )


class TestOptimizationActivity:
    @pytest.mark.asyncio
    async def test_partitions_scenarios_and_unavailable(self) -> None:
        building_id = uuid4()
        scenario = _make_scenario(building_id)
        unavailable = ScenarioUnavailable(
            scenario_model="solar_offset_v1",
            model_version=1,
            building_id=building_id,
            reason="no rooftop data",
        )

        p1, p2 = _patched_session()
        with (
            p1,
            p2,
            patch(
                "services.optimization.service.OptimizationService.generate_scenarios",
                AsyncMock(return_value=[scenario, unavailable]),
            ),
        ):
            result = await optimization_activity(
                AnalysisPipelineInput(
                    tenant_id=str(uuid4()), building_id=str(building_id), correlation_id="c1"
                ),
                ExplainabilityOutput(persisted_finding_ids=[], bundles=[]),
            )

        assert result.scenarios == [scenario]
        assert result.unavailable == [unavailable]

    @pytest.mark.asyncio
    async def test_building_not_found_returns_empty_output(self) -> None:
        from services.optimization.service import BuildingNotFoundError

        p1, p2 = _patched_session()
        with (
            p1,
            p2,
            patch(
                "services.optimization.service.OptimizationService.generate_scenarios",
                AsyncMock(side_effect=BuildingNotFoundError("not found")),
            ),
        ):
            result = await optimization_activity(
                AnalysisPipelineInput(
                    tenant_id=str(uuid4()), building_id=str(uuid4()), correlation_id="c1"
                ),
                ExplainabilityOutput(persisted_finding_ids=[], bundles=[]),
            )

        assert result.scenarios == []
        assert result.unavailable == []

    @pytest.mark.asyncio
    async def test_no_outcomes_returns_empty_output(self) -> None:
        p1, p2 = _patched_session()
        with (
            p1,
            p2,
            patch(
                "services.optimization.service.OptimizationService.generate_scenarios",
                AsyncMock(return_value=[]),
            ),
        ):
            result = await optimization_activity(
                AnalysisPipelineInput(
                    tenant_id=str(uuid4()), building_id=str(uuid4()), correlation_id="c1"
                ),
                ExplainabilityOutput(persisted_finding_ids=[], bundles=[]),
            )

        assert result.scenarios == []
        assert result.unavailable == []
