"""TRD v2.0 §7.1 — Tenant/Admin API data models (tenant + building CRUD,
API key management, sandbox provisioning)."""

from __future__ import annotations

import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class Tenant(BaseModel):
    tenant_id: UUID
    name: str
    isolation_tier: str
    is_sandbox: bool
    cross_tenant_aggregate_opt_in: bool
    created_at: datetime.datetime


class Building(BaseModel):
    building_id: UUID
    tenant_id: UUID
    name: str
    building_type: str
    timezone: str
    climate_zone: str | None = None
    onboarded_at: datetime.datetime


class BuildingCreate(BaseModel):
    name: str
    building_type: str
    timezone: str
    climate_zone: str | None = None


class ApiClient(BaseModel):
    """An OAuth2 client-credentials pair, minus the secret (TRD v2.0 §9.4:
    a secret is never stored or returned as plaintext after issuance)."""

    client_id: UUID
    tenant_id: UUID
    name: str
    tier: str
    created_at: datetime.datetime
    revoked_at: datetime.datetime | None = None


class ApiClientIssued(BaseModel):
    """Returned exactly once, at creation time -- the only moment the
    plaintext client_secret is ever available."""

    client: ApiClient
    client_secret: str = Field(
        ..., description="Plaintext secret. Store it now -- it is not retrievable again."
    )
