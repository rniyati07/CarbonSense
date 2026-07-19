"""ENG-5a — FastAPI dependency chain: JWT validation -> tenant-header
mismatch rejection -> rate limiting -> tenant-scoped DB session.

Every router in apps/api/routers/ builds its handlers on top of
get_tenant_scoped_session (or get_validated_tenant_id alone, for endpoints
that don't touch the DB). No router is expected to call tenant_scope()
directly -- this module is the single place that decision is made, so a
future change to the auth model touches one file, not every router.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.rate_limit import RateLimitExceededError, TenantRateLimiter, get_rate_limiter
from orchestration.events.kafka.producer import CarbonSenseKafkaProducer, EventPublisher
from shared.auth.jwt import InvalidTokenError, TokenClaims, decode_access_token
from shared.auth.tenant_context import tenant_scope
from shared.config.auth import AuthSettings
from shared.config.kafka import KafkaSettings
from shared.database import get_session_factory

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/v1/oauth/token", auto_error=True)

_event_publisher: EventPublisher | None = None


def get_event_publisher() -> EventPublisher:
    """Process-wide singleton -- CarbonSenseKafkaProducer wraps a single
    confluent_kafka.Producer whose background thread and local buffer are
    meant to be shared across requests, not reconstructed per call."""
    global _event_publisher
    if _event_publisher is None:
        _event_publisher = CarbonSenseKafkaProducer(KafkaSettings())
    return _event_publisher


def get_auth_settings() -> AuthSettings:
    return AuthSettings()


async def get_current_claims(
    token: str = Depends(oauth2_scheme),
    settings: AuthSettings = Depends(get_auth_settings),
) -> TokenClaims:
    try:
        return decode_access_token(token, settings)
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


async def get_validated_tenant_id(
    claims: TokenClaims = Depends(get_current_claims),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
) -> UUID:
    """TRD v2.0 §7.2: the tenant_id used downstream is always the validated
    token claim. An X-Tenant-ID header, if present, is checked for
    consistency and the request is rejected on mismatch -- it is never
    itself trusted as the source of truth."""
    if x_tenant_id is not None:
        try:
            header_tenant_id = UUID(x_tenant_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="X-Tenant-ID header is not a valid UUID",
            ) from exc
        if header_tenant_id != claims.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="X-Tenant-ID header does not match the authenticated tenant",
            )
    return claims.tenant_id


async def enforce_rate_limit(
    claims: TokenClaims = Depends(get_current_claims),
    limiter: TenantRateLimiter = Depends(get_rate_limiter),
) -> None:
    try:
        limiter.check(claims.tenant_id, claims.tier)
    except RateLimitExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
            headers={"Retry-After": str(int(exc.retry_after_seconds))},
        ) from exc


async def get_tenant_scoped_session(
    tenant_id: UUID = Depends(get_validated_tenant_id),
    _rate_limit: None = Depends(enforce_rate_limit),
) -> AsyncIterator[AsyncSession]:
    factory = get_session_factory()
    async with factory() as session, tenant_scope(session, tenant_id):
        yield session
        await session.commit()
