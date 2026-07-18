"""ENG-4a — optimization_activity: thin Temporal wrapper around
OptimizationService, proving the "callable as a Temporal workflow step"
half of TRD v2.0 §4's service boundary. The other half (synchronous API
call) has no endpoint to wire into yet -- apps/api is unbuilt (ENG-5) -- so
OptimizationService itself stays framework-agnostic and importable directly
by a future API handler; nothing here is Temporal-specific business logic.
"""

from __future__ import annotations

from uuid import UUID

from temporalio import activity

from orchestration.temporal.dto import (
    AnalysisPipelineInput,
    ExplainabilityOutput,
    OptimizationOutput,
)
from services.optimization.models import OptimizationScenario


@activity.defn
async def optimization_activity(
    input: AnalysisPipelineInput,
    explainability_output: ExplainabilityOutput,
) -> OptimizationOutput:
    """Layer 8: Optimization Engine (ENG-4), run after Root-Cause
    Attribution per TRD v2.0 §4's Temporal-callable mode ("as a Temporal
    workflow step within the main analysis pipeline").

    explainability_output is threaded as a parameter to make the pipeline's
    sequencing dependency explicit (optimization must run after this run's
    findings, if any, are persisted), matching every other activity's
    convention in this workflow -- but OptimizationService queries
    findings fresh from the DB via OptimizationRepository rather than from
    explainability_output.persisted_finding_ids, since ENG-4c's
    justification set is "every real, non-dismissed finding_id for the
    building" (TRD v2.0 §4), not only the ones this specific pipeline run
    happened to create.
    """
    from services.optimization.providers import (
        StaticCarbonIntensityProvider,
        StaticSolarProvider,
    )
    from services.optimization.registry import default_registry
    from services.optimization.repository import OptimizationRepository
    from services.optimization.service import BuildingNotFoundError, OptimizationService
    from shared.auth.tenant_context import tenant_scope
    from shared.database import get_session_factory

    del explainability_output  # sequencing-only, see docstring

    tenant_id = UUID(input.tenant_id)
    building_id = UUID(input.building_id)

    factory = get_session_factory()
    async with factory() as session, tenant_scope(session, tenant_id):
        service = OptimizationService(
            repository=OptimizationRepository(session),
            registry=default_registry(),
            solar_provider=StaticSolarProvider(),
            carbon_provider=StaticCarbonIntensityProvider(),
        )
        try:
            outcomes = await service.generate_scenarios(tenant_id, building_id)
        except BuildingNotFoundError:
            outcomes = []
        await session.commit()

    scenarios = [o for o in outcomes if isinstance(o, OptimizationScenario)]
    unavailable = [o for o in outcomes if not isinstance(o, OptimizationScenario)]
    return OptimizationOutput(scenarios=scenarios, unavailable=unavailable)
