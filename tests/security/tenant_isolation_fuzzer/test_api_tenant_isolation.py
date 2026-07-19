"""ENG-5 — API-layer tenant isolation: proving tenant A cannot access
tenant B's data *through the HTTP API*, not just at the RLS layer
test_rls_enforcement.py already covers. This is the attack surface ENG-5
adds: a spoofed X-Tenant-ID header, a valid-but-wrong-tenant JWT, or a
guessed resource ID belonging to another tenant.

Same real-database fixtures as test_rls_enforcement.py (tenant_a_id,
tenant_b_id, seed_test_data via conftest.py's autouse fixture) -- this
class only adds an HTTP layer (FastAPI TestClient) on top, issuing real
JWTs signed with the same AuthSettings the app itself uses.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from shared.auth.jwt import issue_access_token
from shared.config.auth import AuthSettings


def _token_for(tenant_id: uuid.UUID) -> str:
    token, _expires_in = issue_access_token(
        tenant_id=tenant_id, subject="test-suite", tier="enterprise", settings=AuthSettings()
    )
    return token


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.mark.security
class TestApiTenantIsolation:
    def test_list_findings_never_returns_other_tenants_findings(
        self, client: TestClient, tenant_a_id: uuid.UUID, tenant_b_id: uuid.UUID
    ) -> None:
        response = client.get(
            "/v1/findings", headers={"Authorization": f"Bearer {_token_for(tenant_a_id)}"}
        )
        assert response.status_code == 200
        returned_tenant_ids = {row["tenant_id"] for row in response.json()}
        assert str(tenant_b_id) not in returned_tenant_ids

    def test_get_finding_by_id_rejects_cross_tenant_guess(
        self, client: TestClient, tenant_a_id: uuid.UUID, tenant_b_id: uuid.UUID
    ) -> None:
        """finding_a3333333-... belongs to tenant B per conftest's seed
        data -- tenant A guessing that ID must get 404, never the row."""
        tenant_b_finding_id = "b3333333-3333-3333-3333-333333333333"
        response = client.get(
            f"/v1/findings/{tenant_b_finding_id}",
            headers={"Authorization": f"Bearer {_token_for(tenant_a_id)}"},
        )
        assert response.status_code == 404

    def test_list_buildings_never_returns_other_tenants_buildings(
        self, client: TestClient, tenant_a_id: uuid.UUID, tenant_b_id: uuid.UUID
    ) -> None:
        response = client.get(
            "/v1/tenant/buildings", headers={"Authorization": f"Bearer {_token_for(tenant_a_id)}"}
        )
        assert response.status_code == 200
        returned_tenant_ids = {row["tenant_id"] for row in response.json()}
        assert str(tenant_b_id) not in returned_tenant_ids

    def test_spoofed_tenant_header_is_rejected_not_trusted(
        self, client: TestClient, tenant_a_id: uuid.UUID, tenant_b_id: uuid.UUID
    ) -> None:
        """TRD v2.0 §7.2: an X-Tenant-ID header inconsistent with the JWT's
        tenant claim must be rejected outright -- never silently ignored,
        and never used as the source of truth."""
        response = client.get(
            "/v1/tenant/buildings",
            headers={
                "Authorization": f"Bearer {_token_for(tenant_a_id)}",
                "X-Tenant-ID": str(tenant_b_id),
            },
        )
        assert response.status_code == 403

    def test_consistent_tenant_header_is_accepted(
        self, client: TestClient, tenant_a_id: uuid.UUID
    ) -> None:
        """A header that agrees with the JWT claim is fine -- only a
        mismatch is rejected."""
        response = client.get(
            "/v1/tenant/buildings",
            headers={
                "Authorization": f"Bearer {_token_for(tenant_a_id)}",
                "X-Tenant-ID": str(tenant_a_id),
            },
        )
        assert response.status_code == 200

    def test_missing_token_is_rejected(self, client: TestClient) -> None:
        response = client.get("/v1/findings")
        assert response.status_code in (401, 403)

    def test_forged_token_is_rejected(self, client: TestClient, tenant_b_id: uuid.UUID) -> None:
        """A token signed with a different secret than the server's must
        never be accepted, no matter what tenant_id claim it carries."""
        import jwt as pyjwt

        forged = pyjwt.encode(
            {"tenant_id": str(tenant_b_id), "sub": "attacker", "tier": "enterprise"},
            "wrong-secret",
            algorithm="HS256",
        )
        response = client.get("/v1/findings", headers={"Authorization": f"Bearer {forged}"})
        assert response.status_code == 401
