"""ENG-5a — JWT issuance and validation (TRD v2.0 §7.2).

Every token carries a tenant_id claim, which is the *only* source of truth
tenant-scoping is ever allowed to trust (shared/auth/tenant_context.py's own
docstring: "never from a client-supplied header alone"). This module is
deliberately framework-agnostic (no FastAPI import) so it is reusable by
both the OAuth2 client-credentials issuance path and, if a distinct
dashboard-session issuance path is added later, that path too -- both
converge on the same TokenClaims shape and the same tenant_scope() caller
downstream.
"""

from __future__ import annotations

import datetime
from uuid import UUID

import jwt
from pydantic import BaseModel

from shared.config.auth import AuthSettings


class TokenClaims(BaseModel):
    tenant_id: UUID
    subject: str
    tier: str


class InvalidTokenError(Exception):
    pass


def issue_access_token(
    *,
    tenant_id: UUID,
    subject: str,
    tier: str,
    settings: AuthSettings,
) -> tuple[str, int]:
    """Returns (token, expires_in_seconds)."""
    now = datetime.datetime.now(datetime.UTC)
    expires_in = settings.access_token_ttl_seconds
    payload = {
        "tenant_id": str(tenant_id),
        "sub": subject,
        "tier": tier,
        "iat": now,
        "exp": now + datetime.timedelta(seconds=expires_in),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, expires_in


def decode_access_token(token: str, settings: AuthSettings) -> TokenClaims:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc

    try:
        return TokenClaims(
            tenant_id=UUID(payload["tenant_id"]),
            subject=payload["sub"],
            tier=payload.get("tier", "freemium"),
        )
    except (KeyError, ValueError) as exc:
        raise InvalidTokenError(f"Malformed token claims: {exc}") from exc
