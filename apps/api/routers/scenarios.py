"""ENG-5b/5d — Scenario API (TRD v2.0 §7.1/§7.3): request and retrieve
optimization scenarios, single-building (synchronous) or portfolio
(202 + poll_url + webhook, per §7.3's own literal example).

Single-building GET is a direct, synchronous call into OptimizationService
per TRD v2.0 §4's "Service boundary: ... (a) synchronously via the API for
a fast LP solve on a single building/scenario." Portfolio POST is the
async-delivery example; see apps/api/jobs.py and migration 0008 for why it
uses BackgroundTasks + analysis_jobs rather than a second orchestration
engine competing with Temporal.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_tenant_scoped_session, get_validated_tenant_id
from apps.api.idempotency import get_cached_response, store_response
from apps.api.jobs import AnalysisJobRepository
from apps.api.webhooks import notify_webhooks
from services.optimization.models import PortfolioOptimizationResult, ScenarioOutcome
from services.optimization.providers import StaticCarbonIntensityProvider, StaticSolarProvider
from services.optimization.registry import default_registry
from services.optimization.repository import OptimizationRepository
from services.optimization.service import BuildingNotFoundError, OptimizationService
from shared.auth.tenant_context import tenant_scope
from shared.database import get_session_factory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/scenarios", tags=["scenarios"])

_ANALYZE_ENDPOINT = "POST /v1/scenarios/analyze"


class PortfolioAnalyzeRequest(BaseModel):
    building_ids: list[UUID] = Field(..., min_length=1)


class AnalyzeAcceptedResponse(BaseModel):
    analysis_id: UUID
    status: str
    poll_url: str
    webhook_supported: bool = True


class AnalysisStatusResponse(BaseModel):
    analysis_id: UUID
    status: str
    poll_url: str
    result_url: str | None = None
    error: str | None = None


@router.get("/{building_id}", response_model=list[ScenarioOutcome])
async def get_building_scenarios(
    building_id: UUID,
    tenant_id: UUID = Depends(get_validated_tenant_id),
    session: AsyncSession = Depends(get_tenant_scoped_session),
) -> list[ScenarioOutcome]:
    service = OptimizationService(
        repository=OptimizationRepository(session),
        registry=default_registry(),
        solar_provider=StaticSolarProvider(),
        carbon_provider=StaticCarbonIntensityProvider(),
    )
    try:
        return await service.generate_scenarios(tenant_id, building_id)
    except BuildingNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/analyze", response_model=AnalyzeAcceptedResponse, status_code=status.HTTP_202_ACCEPTED
)
async def analyze_portfolio(
    body: PortfolioAnalyzeRequest,
    background_tasks: BackgroundTasks,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    tenant_id: UUID = Depends(get_validated_tenant_id),
    session: AsyncSession = Depends(get_tenant_scoped_session),
) -> AnalyzeAcceptedResponse:
    if idempotency_key is not None:
        cached = await get_cached_response(session, tenant_id, idempotency_key, _ANALYZE_ENDPOINT)
        if cached is not None:
            _, cached_body = cached
            return AnalyzeAcceptedResponse(**cached_body)

    job_id = await AnalysisJobRepository(session).create(tenant_id, body.building_ids)
    response = AnalyzeAcceptedResponse(
        analysis_id=job_id,
        status="processing",
        poll_url=f"/v1/scenarios/analyze/{job_id}",
    )

    if idempotency_key is not None:
        await store_response(
            session,
            tenant_id,
            idempotency_key,
            _ANALYZE_ENDPOINT,
            status.HTTP_202_ACCEPTED,
            response.model_dump(mode="json"),
        )

    background_tasks.add_task(_run_portfolio_analysis, tenant_id, job_id, body.building_ids)
    return response


@router.get("/analyze/{analysis_id}", response_model=AnalysisStatusResponse)
async def get_analysis_status(
    analysis_id: UUID,
    tenant_id: UUID = Depends(get_validated_tenant_id),
    session: AsyncSession = Depends(get_tenant_scoped_session),
) -> AnalysisStatusResponse:
    job = await AnalysisJobRepository(session).get(tenant_id, analysis_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis job not found")
    return AnalysisStatusResponse(
        analysis_id=analysis_id,
        status=job["status"],
        poll_url=f"/v1/scenarios/analyze/{analysis_id}",
        result_url=(
            f"/v1/scenarios/analyze/{analysis_id}/result" if job["status"] == "completed" else None
        ),
        error=job["error"],
    )


@router.get("/analyze/{analysis_id}/result", response_model=PortfolioOptimizationResult)
async def get_analysis_result(
    analysis_id: UUID,
    tenant_id: UUID = Depends(get_validated_tenant_id),
    session: AsyncSession = Depends(get_tenant_scoped_session),
) -> PortfolioOptimizationResult:
    job = await AnalysisJobRepository(session).get(tenant_id, analysis_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis job not found")
    if job["status"] != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Analysis job is {job['status']}, not yet completed",
        )
    return PortfolioOptimizationResult.model_validate(job["result"])


async def _run_portfolio_analysis(tenant_id: UUID, job_id: UUID, building_ids: list[UUID]) -> None:
    """Runs after the 202 response has been sent (FastAPI BackgroundTasks).
    Opens its own session -- the request-scoped session is not safe to
    reuse once the request/response cycle has ended -- following the exact
    `factory() + tenant_scope()` pattern optimization_activity already
    establishes for Temporal-side callers.
    """
    factory = get_session_factory()
    job_repo: AnalysisJobRepository
    async with factory() as session, tenant_scope(session, tenant_id):
        job_repo = AnalysisJobRepository(session)
        try:
            service = OptimizationService(
                repository=OptimizationRepository(session),
                registry=default_registry(),
                solar_provider=StaticSolarProvider(),
                carbon_provider=StaticCarbonIntensityProvider(),
            )
            result = await service.generate_portfolio(tenant_id, building_ids)
            await job_repo.mark_completed(tenant_id, job_id, result.model_dump(mode="json"))
            await session.commit()
        except Exception as exc:  # noqa: BLE001 -- background task: log + persist, never raise
            logger.exception("Portfolio analysis job %s failed", job_id)
            await job_repo.mark_failed(tenant_id, job_id, str(exc))
            await session.commit()
            return

    async with factory() as session, tenant_scope(session, tenant_id):
        await notify_webhooks(
            session,
            tenant_id,
            "analysis.completed",
            {
                "analysis_id": str(job_id),
                "tenant_id": str(tenant_id),
                "result_url": f"/v1/scenarios/analyze/{job_id}/result",
            },
        )
