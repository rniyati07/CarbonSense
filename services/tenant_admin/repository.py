"""TRD v2.0 §7.1 — Tenant/Admin API data access.

Two access patterns coexist here, deliberately:

- Building/tenant-row/api-client-listing methods run inside an
  already-established tenant_scope(session, tenant_id) block (the caller,
  per the existing dependency-injection convention, has already SET LOCAL
  app.current_tenant_id). Every method still filters by tenant_id
  explicitly in its WHERE clause -- not relying on RLS alone -- because
  api_clients (see migration 0008) intentionally carries no RLS policy.
- get_api_client_by_id() is the one method callable *before* any tenant
  context exists (the OAuth2 token endpoint knows only a client_id), which
  is exactly why api_clients has no RLS policy -- see 0008's docstring.
"""

from __future__ import annotations

import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.tenant_admin.models import ApiClient, Building, Tenant


class TenantAdminRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------ #
    # Tenant
    # ------------------------------------------------------------------ #

    async def get_tenant(self, tenant_id: UUID) -> Tenant | None:
        stmt = text(
            """
            SELECT tenant_id, name, isolation_tier, is_sandbox,
                   cross_tenant_aggregate_opt_in, created_at
            FROM tenants
            WHERE tenant_id = :tenant_id
            """
        )
        result = await self._session.execute(stmt, {"tenant_id": str(tenant_id)})
        row = result.fetchone()
        if row is None:
            return None
        return Tenant(
            tenant_id=row.tenant_id,
            name=row.name,
            isolation_tier=row.isolation_tier,
            is_sandbox=row.is_sandbox,
            cross_tenant_aggregate_opt_in=row.cross_tenant_aggregate_opt_in,
            created_at=row.created_at,
        )

    async def create_sandbox_tenant(self, name: str) -> Tenant:
        stmt = text(
            """
            INSERT INTO tenants (name, isolation_tier, is_sandbox)
            VALUES (:name, 'dedicated_schema', TRUE)
            RETURNING tenant_id, name, isolation_tier, is_sandbox,
                      cross_tenant_aggregate_opt_in, created_at
            """
        )
        result = await self._session.execute(stmt, {"name": name})
        row = result.fetchone()
        assert row is not None
        return Tenant(
            tenant_id=row.tenant_id,
            name=row.name,
            isolation_tier=row.isolation_tier,
            is_sandbox=row.is_sandbox,
            cross_tenant_aggregate_opt_in=row.cross_tenant_aggregate_opt_in,
            created_at=row.created_at,
        )

    # ------------------------------------------------------------------ #
    # Buildings
    # ------------------------------------------------------------------ #

    async def list_buildings(self, tenant_id: UUID) -> list[Building]:
        stmt = text(
            """
            SELECT building_id, tenant_id, name, building_type, timezone,
                   climate_zone, onboarded_at
            FROM buildings
            WHERE tenant_id = :tenant_id
            ORDER BY onboarded_at DESC
            """
        )
        result = await self._session.execute(stmt, {"tenant_id": str(tenant_id)})
        return [
            Building(
                building_id=row.building_id,
                tenant_id=row.tenant_id,
                name=row.name,
                building_type=row.building_type,
                timezone=row.timezone,
                climate_zone=row.climate_zone,
                onboarded_at=row.onboarded_at,
            )
            for row in result.fetchall()
        ]

    async def get_building(self, tenant_id: UUID, building_id: UUID) -> Building | None:
        stmt = text(
            """
            SELECT building_id, tenant_id, name, building_type, timezone,
                   climate_zone, onboarded_at
            FROM buildings
            WHERE tenant_id = :tenant_id AND building_id = :building_id
            """
        )
        result = await self._session.execute(
            stmt, {"tenant_id": str(tenant_id), "building_id": str(building_id)}
        )
        row = result.fetchone()
        if row is None:
            return None
        return Building(
            building_id=row.building_id,
            tenant_id=row.tenant_id,
            name=row.name,
            building_type=row.building_type,
            timezone=row.timezone,
            climate_zone=row.climate_zone,
            onboarded_at=row.onboarded_at,
        )

    async def create_building(
        self,
        tenant_id: UUID,
        name: str,
        building_type: str,
        timezone: str,
        climate_zone: str | None,
    ) -> Building:
        stmt = text(
            """
            INSERT INTO buildings (tenant_id, name, building_type, timezone, climate_zone)
            VALUES (:tenant_id, :name, :building_type, :timezone, :climate_zone)
            RETURNING building_id, tenant_id, name, building_type, timezone,
                      climate_zone, onboarded_at
            """
        )
        result = await self._session.execute(
            stmt,
            {
                "tenant_id": str(tenant_id),
                "name": name,
                "building_type": building_type,
                "timezone": timezone,
                "climate_zone": climate_zone,
            },
        )
        row = result.fetchone()
        assert row is not None
        return Building(
            building_id=row.building_id,
            tenant_id=row.tenant_id,
            name=row.name,
            building_type=row.building_type,
            timezone=row.timezone,
            climate_zone=row.climate_zone,
            onboarded_at=row.onboarded_at,
        )

    async def delete_building(self, tenant_id: UUID, building_id: UUID) -> bool:
        stmt = text(
            "DELETE FROM buildings WHERE tenant_id = :tenant_id AND building_id = :building_id"
        )
        result = await self._session.execute(
            stmt, {"tenant_id": str(tenant_id), "building_id": str(building_id)}
        )
        # AsyncSession.execute()'s declared return type is the generic
        # Result[Any], whose stub doesn't carry .rowcount -- it's really a
        # CursorResult at runtime (this is a known SQLAlchemy async-stub
        # gap, not a real type error).
        return bool(result.rowcount)  # type: ignore[attr-defined]

    # ------------------------------------------------------------------ #
    # API clients (OAuth2 client-credentials / "API keys")
    # ------------------------------------------------------------------ #

    async def create_api_client(
        self, tenant_id: UUID, name: str, tier: str, client_secret_hash: str
    ) -> ApiClient:
        stmt = text(
            """
            INSERT INTO api_clients (tenant_id, name, tier, client_secret_hash)
            VALUES (:tenant_id, :name, :tier, :client_secret_hash)
            RETURNING client_id, tenant_id, name, tier, created_at, revoked_at
            """
        )
        result = await self._session.execute(
            stmt,
            {
                "tenant_id": str(tenant_id),
                "name": name,
                "tier": tier,
                "client_secret_hash": client_secret_hash,
            },
        )
        row = result.fetchone()
        assert row is not None
        return ApiClient(
            client_id=row.client_id,
            tenant_id=row.tenant_id,
            name=row.name,
            tier=row.tier,
            created_at=row.created_at,
            revoked_at=row.revoked_at,
        )

    async def list_api_clients(self, tenant_id: UUID) -> list[ApiClient]:
        stmt = text(
            """
            SELECT client_id, tenant_id, name, tier, created_at, revoked_at
            FROM api_clients
            WHERE tenant_id = :tenant_id
            ORDER BY created_at DESC
            """
        )
        result = await self._session.execute(stmt, {"tenant_id": str(tenant_id)})
        return [
            ApiClient(
                client_id=row.client_id,
                tenant_id=row.tenant_id,
                name=row.name,
                tier=row.tier,
                created_at=row.created_at,
                revoked_at=row.revoked_at,
            )
            for row in result.fetchall()
        ]

    async def revoke_api_client(self, tenant_id: UUID, client_id: UUID) -> bool:
        stmt = text(
            """
            UPDATE api_clients SET revoked_at = :now
            WHERE tenant_id = :tenant_id AND client_id = :client_id AND revoked_at IS NULL
            """
        )
        result = await self._session.execute(
            stmt,
            {
                "now": datetime.datetime.now(datetime.UTC),
                "tenant_id": str(tenant_id),
                "client_id": str(client_id),
            },
        )
        return bool(result.rowcount)  # type: ignore[attr-defined]  # see delete_building()

    async def get_api_client_by_id(self, client_id: UUID) -> tuple[ApiClient, str] | None:
        """Pre-auth lookup (no tenant context yet) -- see module docstring."""
        stmt = text(
            """
            SELECT client_id, tenant_id, name, tier, created_at, revoked_at, client_secret_hash
            FROM api_clients
            WHERE client_id = :client_id
            """
        )
        result = await self._session.execute(stmt, {"client_id": str(client_id)})
        row = result.fetchone()
        if row is None:
            return None
        client = ApiClient(
            client_id=row.client_id,
            tenant_id=row.tenant_id,
            name=row.name,
            tier=row.tier,
            created_at=row.created_at,
            revoked_at=row.revoked_at,
        )
        return client, row.client_secret_hash
