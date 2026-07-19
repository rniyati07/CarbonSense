"""ENG-5b/5e — Tenant/Admin API (TRD v2.0 §7.1/§7.4): tenant and building
CRUD, API key management, sandbox provisioning. Thin wrapper over
TenantAdminService/SandboxProvisioningService.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import (
    get_current_claims,
    get_tenant_scoped_session,
    get_validated_tenant_id,
)
from services.tenant_admin.models import ApiClient, ApiClientIssued, Building, Tenant
from services.tenant_admin.repository import TenantAdminRepository
from services.tenant_admin.service import SandboxProvisioningService, TenantAdminService
from shared.auth.jwt import TokenClaims
from shared.database import get_session

router = APIRouter(prefix="/v1/tenant", tags=["tenant"])


class BuildingCreateRequest(BaseModel):
    name: str
    building_type: str
    timezone: str
    climate_zone: str | None = None


class ApiKeyCreateRequest(BaseModel):
    name: str
    tier: str = "freemium"


class SandboxCreateRequest(BaseModel):
    name: str


@router.get("/me", response_model=Tenant)
async def get_my_tenant(
    tenant_id: UUID = Depends(get_validated_tenant_id),
    session: AsyncSession = Depends(get_tenant_scoped_session),
) -> Tenant:
    service = TenantAdminService(TenantAdminRepository(session))
    return await service.get_tenant(tenant_id)


@router.get("/buildings", response_model=list[Building])
async def list_buildings(
    tenant_id: UUID = Depends(get_validated_tenant_id),
    session: AsyncSession = Depends(get_tenant_scoped_session),
) -> list[Building]:
    service = TenantAdminService(TenantAdminRepository(session))
    return await service.list_buildings(tenant_id)


@router.post("/buildings", response_model=Building, status_code=status.HTTP_201_CREATED)
async def create_building(
    body: BuildingCreateRequest,
    tenant_id: UUID = Depends(get_validated_tenant_id),
    session: AsyncSession = Depends(get_tenant_scoped_session),
) -> Building:
    service = TenantAdminService(TenantAdminRepository(session))
    return await service.create_building(
        tenant_id, body.name, body.building_type, body.timezone, body.climate_zone
    )


@router.delete("/buildings/{building_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_building(
    building_id: UUID,
    tenant_id: UUID = Depends(get_validated_tenant_id),
    session: AsyncSession = Depends(get_tenant_scoped_session),
) -> None:
    service = TenantAdminService(TenantAdminRepository(session))
    await service.delete_building(tenant_id, building_id)


@router.get("/api-keys", response_model=list[ApiClient])
async def list_api_keys(
    tenant_id: UUID = Depends(get_validated_tenant_id),
    session: AsyncSession = Depends(get_tenant_scoped_session),
) -> list[ApiClient]:
    service = TenantAdminService(TenantAdminRepository(session))
    return await service.list_api_clients(tenant_id)


@router.post("/api-keys", response_model=ApiClientIssued, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    body: ApiKeyCreateRequest,
    tenant_id: UUID = Depends(get_validated_tenant_id),
    session: AsyncSession = Depends(get_tenant_scoped_session),
) -> ApiClientIssued:
    service = TenantAdminService(TenantAdminRepository(session))
    return await service.issue_api_client(tenant_id, body.name, body.tier)


@router.delete("/api-keys/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    client_id: UUID,
    tenant_id: UUID = Depends(get_validated_tenant_id),
    session: AsyncSession = Depends(get_tenant_scoped_session),
) -> None:
    service = TenantAdminService(TenantAdminRepository(session))
    await service.revoke_api_client(tenant_id, client_id)


@router.post("/sandbox", response_model=Tenant, status_code=status.HTTP_201_CREATED)
async def provision_sandbox(
    body: SandboxCreateRequest,
    _claims: TokenClaims = Depends(get_current_claims),
    session: AsyncSession = Depends(get_session),
) -> Tenant:
    """TRD v2.0 §7.4: provisions a brand-new, isolated sandbox tenant --
    deliberately not scoped to the caller's own tenant_id (it creates a
    different tenant row entirely), so this uses a plain session rather
    than get_tenant_scoped_session. Any authenticated caller may provision
    a sandbox; self-serve-vs-gated rollout policy is explicitly out of TRD
    scope (Appendix B, OQ-6)."""
    repository = TenantAdminRepository(session)
    service = SandboxProvisioningService(session, repository)
    tenant = await service.provision(body.name)
    await session.commit()
    return tenant
