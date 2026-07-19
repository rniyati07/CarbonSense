"""ENG-5c — OAuth2 client-credentials token issuance (TRD v2.0 §7.2).

Server-to-server integrators exchange a client_id/client_secret pair
(issued via the Tenant/Admin API's api-keys endpoints) for a short-lived
JWT carrying the tenant_id claim every other endpoint in this API trusts.
This is the *only* unauthenticated endpoint in apps/api -- everything else
sits behind apps.api.dependencies.get_current_claims.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from services.tenant_admin.repository import TenantAdminRepository
from shared.auth.jwt import issue_access_token
from shared.auth.secrets import verify_client_secret
from shared.config.auth import AuthSettings
from shared.database import get_session

router = APIRouter(tags=["oauth"])

_INVALID_CREDENTIALS_DETAIL = "Invalid client_id or client_secret"


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 -- OAuth2 field name, not a credential
    expires_in: int


def get_auth_settings() -> AuthSettings:
    return AuthSettings()


@router.post("/v1/oauth/token", response_model=TokenResponse)
async def issue_token(
    grant_type: Annotated[str, Form()],
    client_id: Annotated[str, Form()],
    client_secret: Annotated[str, Form()],
    session: AsyncSession = Depends(get_session),
    settings: AuthSettings = Depends(get_auth_settings),
) -> TokenResponse:
    if grant_type != "client_credentials":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported grant_type -- only client_credentials is supported",
        )

    try:
        client_uuid = UUID(client_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=_INVALID_CREDENTIALS_DETAIL
        ) from exc

    repository = TenantAdminRepository(session)
    record = await repository.get_api_client_by_id(client_uuid)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=_INVALID_CREDENTIALS_DETAIL
        )

    client, secret_hash = record
    if client.revoked_at is not None or not verify_client_secret(client_secret, secret_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=_INVALID_CREDENTIALS_DETAIL
        )

    token, expires_in = issue_access_token(
        tenant_id=client.tenant_id,
        subject=str(client.client_id),
        tier=client.tier,
        settings=settings,
    )
    return TokenResponse(access_token=token, expires_in=expires_in)
