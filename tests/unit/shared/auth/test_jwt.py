from __future__ import annotations

import uuid

import jwt as pyjwt
import pytest

from shared.auth.jwt import InvalidTokenError, decode_access_token, issue_access_token
from shared.config.auth import AuthSettings


@pytest.mark.unit
class TestIssueAndDecodeAccessToken:
    def test_roundtrip_preserves_claims(self) -> None:
        settings = AuthSettings()
        tenant_id = uuid.uuid4()

        token, expires_in = issue_access_token(
            tenant_id=tenant_id, subject="client-123", tier="enterprise", settings=settings
        )
        claims = decode_access_token(token, settings)

        assert claims.tenant_id == tenant_id
        assert claims.subject == "client-123"
        assert claims.tier == "enterprise"
        assert expires_in == settings.access_token_ttl_seconds

    def test_rejects_token_signed_with_wrong_secret(self) -> None:
        settings = AuthSettings()
        forged = pyjwt.encode(
            {"tenant_id": str(uuid.uuid4()), "sub": "attacker", "tier": "enterprise"},
            "not-the-real-secret",
            algorithm="HS256",
        )
        with pytest.raises(InvalidTokenError):
            decode_access_token(forged, settings)

    def test_rejects_expired_token(self) -> None:
        settings = AuthSettings()
        expired = pyjwt.encode(
            {
                "tenant_id": str(uuid.uuid4()),
                "sub": "client-123",
                "tier": "freemium",
                "exp": 1,  # 1970-01-01, long expired
            },
            settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
        )
        with pytest.raises(InvalidTokenError):
            decode_access_token(expired, settings)

    def test_rejects_token_missing_tenant_id_claim(self) -> None:
        settings = AuthSettings()
        malformed = pyjwt.encode(
            {"sub": "client-123", "tier": "freemium"},
            settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
        )
        with pytest.raises(InvalidTokenError):
            decode_access_token(malformed, settings)

    def test_rejects_non_uuid_tenant_id_claim(self) -> None:
        settings = AuthSettings()
        malformed = pyjwt.encode(
            {"tenant_id": "not-a-uuid", "sub": "client-123", "tier": "freemium"},
            settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
        )
        with pytest.raises(InvalidTokenError):
            decode_access_token(malformed, settings)

    def test_defaults_tier_to_freemium_when_absent(self) -> None:
        settings = AuthSettings()
        token = pyjwt.encode(
            {"tenant_id": str(uuid.uuid4()), "sub": "client-123"},
            settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
        )
        claims = decode_access_token(token, settings)
        assert claims.tier == "freemium"
