"""TRD v2.0 §7.1/§7.4 — TenantAdminService: tenant/building CRUD, API key
(OAuth2 client-credentials) issuance, and partner sandbox provisioning.

No Temporal or FastAPI import -- same framework-agnostic shape as
OptimizationService/ReportService, callable directly from apps/api routers.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.tenant_admin.models import ApiClient, ApiClientIssued, Building, Tenant
from services.tenant_admin.repository import TenantAdminRepository
from shared.auth.secrets import generate_client_secret, hash_client_secret


class TenantNotFoundError(Exception):
    pass


class BuildingNotFoundError(Exception):
    pass


class TenantAdminService:
    def __init__(self, repository: TenantAdminRepository) -> None:
        self._repository = repository

    async def get_tenant(self, tenant_id: UUID) -> Tenant:
        tenant = await self._repository.get_tenant(tenant_id)
        if tenant is None:
            raise TenantNotFoundError(f"Tenant {tenant_id} not found.")
        return tenant

    async def list_buildings(self, tenant_id: UUID) -> list[Building]:
        return await self._repository.list_buildings(tenant_id)

    async def create_building(
        self,
        tenant_id: UUID,
        name: str,
        building_type: str,
        timezone: str,
        climate_zone: str | None = None,
    ) -> Building:
        return await self._repository.create_building(
            tenant_id, name, building_type, timezone, climate_zone
        )

    async def delete_building(self, tenant_id: UUID, building_id: UUID) -> None:
        deleted = await self._repository.delete_building(tenant_id, building_id)
        if not deleted:
            raise BuildingNotFoundError(f"Building {building_id} not found for this tenant.")

    async def issue_api_client(self, tenant_id: UUID, name: str, tier: str) -> ApiClientIssued:
        """Creates a new OAuth2 client-credentials pair. The plaintext
        secret is returned exactly once -- only client_secret_hash is
        ever persisted (TRD v2.0 §9.4)."""
        plaintext_secret = generate_client_secret()
        secret_hash = hash_client_secret(plaintext_secret)
        client = await self._repository.create_api_client(tenant_id, name, tier, secret_hash)
        return ApiClientIssued(client=client, client_secret=plaintext_secret)

    async def list_api_clients(self, tenant_id: UUID) -> list[ApiClient]:
        return await self._repository.list_api_clients(tenant_id)

    async def revoke_api_client(self, tenant_id: UUID, client_id: UUID) -> bool:
        return await self._repository.revoke_api_client(tenant_id, client_id)


class SandboxProvisioningService:
    """TRD v2.0 §7.4 — provisions an isolated, dedicated-tier tenant seeded
    with synthetic building data, running the identical API surface and
    service code as production (not a separate mocked API). Owns its own
    session (not tenant-scoped -- provisioning a tenant necessarily
    predates that tenant having an RLS context; every synthetic row it
    inserts explicitly carries the newly-created tenant_id, matching the
    same "always-filter-explicitly" discipline TenantAdminRepository uses
    for the RLS-exempt api_clients table).
    """

    def __init__(self, session: AsyncSession, repository: TenantAdminRepository) -> None:
        self._session = session
        self._repository = repository

    async def provision(self, name: str) -> Tenant:
        tenant = await self._repository.create_sandbox_tenant(name)
        building = await self._repository.create_building(
            tenant_id=tenant.tenant_id,
            name="Synthetic Demo Building",
            building_type="office",
            timezone="Asia/Kolkata",
            climate_zone="tropical_wet_dry",
        )
        await self._seed_synthetic_readings(tenant.tenant_id, building.building_id)
        return tenant

    async def _seed_synthetic_readings(self, tenant_id: UUID, building_id: UUID) -> None:
        circuits_stmt = text(
            """
            INSERT INTO submeter_circuits (tenant_id, building_id, circuit_type, label)
            VALUES
                (:tenant_id, :building_id, 'main', 'Main Panel'),
                (:tenant_id, :building_id, 'hvac', 'HVAC System')
            RETURNING circuit_id
            """
        )
        result = await self._session.execute(
            circuits_stmt, {"tenant_id": str(tenant_id), "building_id": str(building_id)}
        )
        circuit_ids = [row.circuit_id for row in result.fetchall()]

        readings_stmt = text(
            """
            INSERT INTO normalized_readings
                (tenant_id, circuit_id, ts, kwh, is_peak_hour, data_quality_status)
            SELECT
                :tenant_id,
                :circuit_id,
                gs.ts,
                20 + 15 * sin(extract(hour from gs.ts) / 24.0 * 2 * pi()),
                extract(hour from gs.ts) BETWEEN 9 AND 18,
                'pass'
            FROM generate_series(
                now() - interval '48 hours', now(), interval '1 hour'
            ) AS gs(ts)
            """
        )
        for circuit_id in circuit_ids:
            await self._session.execute(
                readings_stmt, {"tenant_id": str(tenant_id), "circuit_id": str(circuit_id)}
            )


__all__ = [
    "BuildingNotFoundError",
    "SandboxProvisioningService",
    "TenantAdminService",
    "TenantNotFoundError",
]
