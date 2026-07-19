"""ENG-5b — Findings API (TRD v2.0 §7.1): retrieve findings + Explainability
Bundles, filter by building/status/confidence. Thin wrapper over
FindingQueryRepository -- no business logic, the canonical Finding/
ExplainabilityBundle models (services.rules_engine.models,
services.explainability.models) are returned directly as response schemas,
per the "no duplicate DTOs" constraint.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_tenant_scoped_session, get_validated_tenant_id
from services.rules_engine.models import Finding
from services.rules_engine.repository import FindingQueryRepository

router = APIRouter(prefix="/v1/findings", tags=["findings"])


@router.get("", response_model=list[Finding])
async def list_findings(
    building_id: UUID | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    min_confidence: float | None = Query(default=None, ge=0.0, le=1.0),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    tenant_id: UUID = Depends(get_validated_tenant_id),
    session: AsyncSession = Depends(get_tenant_scoped_session),
) -> list[Finding]:
    repository = FindingQueryRepository(session)
    return await repository.list_findings(
        tenant_id=tenant_id,
        building_id=building_id,
        status=status_filter,
        min_confidence=min_confidence,
        limit=limit,
        offset=offset,
    )


@router.get("/{finding_id}", response_model=Finding)
async def get_finding(
    finding_id: UUID,
    tenant_id: UUID = Depends(get_validated_tenant_id),
    session: AsyncSession = Depends(get_tenant_scoped_session),
) -> Finding:
    repository = FindingQueryRepository(session)
    finding = await repository.get_finding(tenant_id, finding_id)
    if finding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Finding not found")
    return finding
