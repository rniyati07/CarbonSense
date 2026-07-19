"""ENG-5b — Reporting API (TRD v2.0 §7.1): generate/retrieve exportable
reports (PDF or structured JSON). Thin wrapper over ReportService -- the
router's job is assembling a ReportingRequest from already-persisted
findings/scenarios, nothing more; the LLM narration, retry-and-fallback,
and PDF rendering all stay inside services/reporting exactly as ENG-3h/5's
predecessors built them.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

import anthropic
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_tenant_scoped_session, get_validated_tenant_id
from services.optimization.models import OptimizationScenario
from services.optimization.providers import StaticCarbonIntensityProvider, StaticSolarProvider
from services.optimization.registry import default_registry
from services.optimization.repository import OptimizationRepository
from services.optimization.service import OptimizationService
from services.reporting.models import ActionPlan, FindingWithBundle, ReportingRequest
from services.reporting.report_service import ReportService
from services.rules_engine.repository import FindingQueryRepository
from services.tenant_admin.repository import TenantAdminRepository

router = APIRouter(prefix="/v1/reports", tags=["reports"])

_anthropic_client: anthropic.Anthropic | None = None


def get_anthropic_client() -> anthropic.Anthropic:
    """Process-wide singleton. Reads ANTHROPIC_API_KEY from the environment
    (the SDK's own convention) -- no wrapper settings class needed."""
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = anthropic.Anthropic()
    return _anthropic_client


async def _build_reporting_request(
    session: AsyncSession, tenant_id: UUID, building_id: UUID
) -> ReportingRequest:
    building = await TenantAdminRepository(session).get_building(tenant_id, building_id)
    if building is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Building not found")

    findings = await FindingQueryRepository(session).list_findings(
        tenant_id=tenant_id, building_id=building_id, status="open", limit=200
    )
    if not findings:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No open findings for this building -- nothing to report on",
        )

    optimization_service = OptimizationService(
        repository=OptimizationRepository(session),
        registry=default_registry(),
        solar_provider=StaticSolarProvider(),
        carbon_provider=StaticCarbonIntensityProvider(),
    )
    outcomes = await optimization_service.generate_scenarios(tenant_id, building_id)
    scenarios = [o for o in outcomes if isinstance(o, OptimizationScenario)]

    return ReportingRequest(
        findings=[
            FindingWithBundle(
                finding_id=f.finding_id,
                building_id=f.building_id,
                circuit_id=f.circuit_id,
                layer_origin=f.layer_origin,
                confidence=f.confidence if f.confidence is not None else 0.0,
                explainability_bundle=f.explainability_bundle,
            )
            for f in findings
        ],
        optimization_scenarios=scenarios,
        building_name=building.name,
        tenant_id=tenant_id,
    )


@router.get("/{building_id}", response_model=None)
async def get_report(
    building_id: UUID,
    report_format: Literal["json", "pdf"] = Query(default="json", alias="format"),
    tenant_id: UUID = Depends(get_validated_tenant_id),
    session: AsyncSession = Depends(get_tenant_scoped_session),
    anthropic_client: anthropic.Anthropic = Depends(get_anthropic_client),
) -> ActionPlan | Response:
    request = await _build_reporting_request(session, tenant_id, building_id)
    service = ReportService(anthropic_client=anthropic_client)

    # ReportService is synchronous (a blocking Anthropic API call, and for
    # PDF, blocking weasyprint rendering) -- run_in_threadpool keeps that
    # off the event loop so it doesn't stall other tenants' requests.
    if report_format == "pdf":
        pdf_bytes = await run_in_threadpool(
            service.generate_pdf, request, building_name=request.building_name
        )
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="report-{building_id}.pdf"'},
        )

    return await run_in_threadpool(service.generate_action_plan, request)
