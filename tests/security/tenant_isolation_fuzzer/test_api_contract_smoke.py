"""ENG-5b DoD — "All six endpoint groups pass contract tests." Runs
against the same real, migrated TimescaleDB as test_rls_enforcement.py and
test_api_tenant_isolation.py (conftest.py's tenant_a_id/tenant_b_id/
seed_test_data), proving each router group is actually wired end-to-end --
not mocked plumbing that could pass while the real DB path is broken.

Reports is deliberately tested only on its two 404 paths (unknown building,
building with no open findings) -- the success path calls a real Anthropic
API and is already covered at the unit level by services/reporting's own
tests with a mocked client; making a real LLM call from a CI contract test
would be flaky and costly for no additional wiring confidence.
"""

from __future__ import annotations

import io
import uuid

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from shared.auth.jwt import issue_access_token
from shared.config.auth import AuthSettings


def _token_for(tenant_id: uuid.UUID) -> str:
    token, _ = issue_access_token(
        tenant_id=tenant_id, subject="test-suite", tier="enterprise", settings=AuthSettings()
    )
    return token


def _auth(tenant_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token_for(tenant_id)}"}


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.mark.security
class TestTenantAdminContract:
    def test_api_key_issue_list_revoke_roundtrip(
        self, client: TestClient, tenant_a_id: uuid.UUID
    ) -> None:
        create = client.post(
            "/v1/tenant/api-keys",
            json={"name": "integration-test-key", "tier": "integrator"},
            headers=_auth(tenant_a_id),
        )
        assert create.status_code == 201
        body = create.json()
        assert body["client_secret"]
        client_id = body["client"]["client_id"]

        listing = client.get("/v1/tenant/api-keys", headers=_auth(tenant_a_id))
        assert listing.status_code == 200
        assert any(c["client_id"] == client_id for c in listing.json())

        revoke = client.delete(f"/v1/tenant/api-keys/{client_id}", headers=_auth(tenant_a_id))
        assert revoke.status_code == 204

    def test_sandbox_provisioning(self, client: TestClient, tenant_a_id: uuid.UUID) -> None:
        response = client.post(
            "/v1/tenant/sandbox",
            json={"name": "contract-test-sandbox"},
            headers=_auth(tenant_a_id),
        )
        assert response.status_code == 201
        body = response.json()
        assert body["is_sandbox"] is True
        assert body["tenant_id"] != str(tenant_a_id)


@pytest.mark.security
class TestFeedbackContract:
    def test_submit_feedback_for_existing_finding(
        self, client: TestClient, tenant_a_id: uuid.UUID
    ) -> None:
        finding_a = "a3333333-3333-3333-3333-333333333333"
        response = client.post(
            "/v1/feedback",
            json={"finding_id": finding_a, "action": "confirmed"},
            headers=_auth(tenant_a_id),
        )
        assert response.status_code == 200
        assert response.json()["finding_id"] == finding_a


@pytest.mark.security
class TestScenarioContract:
    def test_single_building_scenarios_returns_a_list(
        self, client: TestClient, tenant_a_id: uuid.UUID
    ) -> None:
        building_a = "a1111111-1111-1111-1111-111111111111"
        response = client.get(f"/v1/scenarios/{building_a}", headers=_auth(tenant_a_id))
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_portfolio_analyze_202_then_pollable(
        self, client: TestClient, tenant_a_id: uuid.UUID
    ) -> None:
        building_a = "a1111111-1111-1111-1111-111111111111"
        accepted = client.post(
            "/v1/scenarios/analyze",
            json={"building_ids": [building_a]},
            headers=_auth(tenant_a_id),
        )
        assert accepted.status_code == 202
        body = accepted.json()
        analysis_id = body["analysis_id"]
        assert body["poll_url"] == f"/v1/scenarios/analyze/{analysis_id}"

        status_response = client.get(
            f"/v1/scenarios/analyze/{analysis_id}", headers=_auth(tenant_a_id)
        )
        assert status_response.status_code == 200
        assert status_response.json()["status"] in ("processing", "completed", "failed")


@pytest.mark.security
class TestIngestionContract:
    def test_csv_upload_then_batch_status_pollable(
        self, client: TestClient, tenant_a_id: uuid.UUID
    ) -> None:
        building_a = "a1111111-1111-1111-1111-111111111111"
        csv_content = (
            "meter_id,timestamp,kwh,circuit_type\n"
            "contract-test-meter,2026-06-01T00:00:00Z,10.5,hvac\n"
        )
        files = {"file": ("readings.csv", io.BytesIO(csv_content.encode()), "text/csv")}
        response = client.post(
            f"/v1/ingestion/csv?building_id={building_a}",
            files=files,
            headers=_auth(tenant_a_id),
        )
        assert response.status_code == 202
        batch_id = response.json()["batch_id"]

        status_response = client.get(
            f"/v1/ingestion/batches/{batch_id}", headers=_auth(tenant_a_id)
        )
        assert status_response.status_code == 200
        assert status_response.json()["batch_id"] == batch_id


@pytest.mark.security
class TestReportsContract:
    def test_unknown_building_is_404(self, client: TestClient, tenant_a_id: uuid.UUID) -> None:
        response = client.get(f"/v1/reports/{uuid.uuid4()}", headers=_auth(tenant_a_id))
        assert response.status_code == 404

    def test_building_with_no_open_findings_is_404(
        self, client: TestClient, tenant_a_id: uuid.UUID
    ) -> None:
        created = client.post(
            "/v1/tenant/buildings",
            json={"name": "Empty Building", "building_type": "office", "timezone": "UTC"},
            headers=_auth(tenant_a_id),
        )
        assert created.status_code == 201
        building_id = created.json()["building_id"]

        response = client.get(f"/v1/reports/{building_id}", headers=_auth(tenant_a_id))
        assert response.status_code == 404
