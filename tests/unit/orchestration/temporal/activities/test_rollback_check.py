from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from models.evaluation.rollback import RollbackDecision
from orchestration.temporal.activities.rollback_check import rollback_check_activity
from orchestration.temporal.dto import RollbackCheckInput


def _patched_session():
    mock_session = AsyncMock()

    @asynccontextmanager
    async def fake_factory_cm():
        yield mock_session

    def fake_factory():
        return fake_factory_cm

    @asynccontextmanager
    async def fake_tenant_scope(session, tenant_id):
        yield session

    return (
        patch("shared.database.get_session_factory", fake_factory),
        patch("shared.auth.tenant_context.tenant_scope", fake_tenant_scope),
    )


@pytest.mark.unit
class TestRollbackCheckActivity:
    @pytest.mark.asyncio
    async def test_reports_no_rollback(self) -> None:
        p1, p2 = _patched_session()
        with (
            p1,
            p2,
            patch("temporalio.activity.heartbeat"),
            patch(
                "models.evaluation.rollback.RollbackMonitor.check_and_rollback",
                AsyncMock(
                    return_value=RollbackDecision(rolled_back=False, reason="within ceiling")
                ),
            ),
        ):
            result = await rollback_check_activity(
                RollbackCheckInput(
                    tenant_id=str(uuid4()), building_id=str(uuid4()), model_type="isolation_forest"
                )
            )

        assert result.step_name == "rollback_check"
        assert result.status == "completed"
        assert "rolled_back=False" in result.detail

    @pytest.mark.asyncio
    async def test_reports_rollback_taken(self) -> None:
        p1, p2 = _patched_session()
        with (
            p1,
            p2,
            patch("temporalio.activity.heartbeat"),
            patch(
                "models.evaluation.rollback.RollbackMonitor.check_and_rollback",
                AsyncMock(
                    return_value=RollbackDecision(
                        rolled_back=True, reason="fp_rate exceeded", new_champion_version="1"
                    )
                ),
            ),
        ):
            result = await rollback_check_activity(
                RollbackCheckInput(
                    tenant_id=str(uuid4()), building_id=str(uuid4()), model_type="autoencoder"
                )
            )

        assert result.status == "completed"
        assert "rolled_back=True" in result.detail
