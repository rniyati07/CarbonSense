from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from orchestration.temporal.activities.retraining_stub import retraining_activity
from orchestration.temporal.dto import RetrainingInput
from pipelines.training.train_and_evaluate import (
    ModelTrainingOutcome,
    TrainAndEvaluateSummary,
)
from services.ml_ensemble.models import TrainingArtifact, TrainingRunResult
from services.tenant_admin.models import Building


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


def _make_building(tenant_id, building_id) -> Building:
    import datetime

    return Building(
        building_id=building_id,
        tenant_id=tenant_id,
        name="Test Building",
        building_type="office",
        timezone="UTC",
        onboarded_at=datetime.datetime.now(datetime.UTC),
    )


def _make_outcome(model_type: str, tenant_id, building_id, approved: bool) -> ModelTrainingOutcome:
    from models.evaluation.promotion_gate import PromotionDecision

    artifact = TrainingArtifact(run_id="r1", artifact_path=model_type, artifact_uri="uri")
    result = TrainingRunResult(
        tenant_id=tenant_id,
        building_id=building_id,
        model_type=model_type,
        mlflow_run_id="r1",
        model_artifact=artifact,
        scaler_artifact=artifact,
        n_training_samples=10,
        registered_version="1",
    )
    return ModelTrainingOutcome(
        result=result, decision=PromotionDecision(approved=approved, reason="x")
    )


@pytest.mark.unit
class TestRetrainingActivity:
    @pytest.mark.asyncio
    async def test_skipped_when_building_not_found(self) -> None:
        p1, p2 = _patched_session()
        with (
            p1,
            p2,
            patch("temporalio.activity.heartbeat"),
            patch(
                "services.tenant_admin.repository.TenantAdminRepository.get_building",
                AsyncMock(return_value=None),
            ),
        ):
            result = await retraining_activity(
                RetrainingInput(
                    tenant_id=str(uuid4()), building_id=str(uuid4()), trigger="calendar"
                )
            )

        assert result.status == "skipped"
        assert "not found" in result.detail.lower()

    @pytest.mark.asyncio
    async def test_completed_summarizes_promotions(self) -> None:
        tenant_id, building_id = uuid4(), uuid4()
        building = _make_building(tenant_id, building_id)
        summary = TrainAndEvaluateSummary(
            tenant_id=tenant_id,
            building_id=building_id,
            trigger="drift",
            n_features_used=42,
            outcomes=[
                _make_outcome("isolation_forest", tenant_id, building_id, approved=True),
                _make_outcome("autoencoder", tenant_id, building_id, approved=False),
            ],
        )

        p1, p2 = _patched_session()
        with (
            p1,
            p2,
            patch("temporalio.activity.heartbeat"),
            patch(
                "services.tenant_admin.repository.TenantAdminRepository.get_building",
                AsyncMock(return_value=building),
            ),
            patch(
                "pipelines.training.train_and_evaluate.train_and_evaluate",
                AsyncMock(return_value=summary),
            ),
        ):
            result = await retraining_activity(
                RetrainingInput(
                    tenant_id=str(tenant_id), building_id=str(building_id), trigger="drift"
                )
            )

        assert result.status == "completed"
        assert "isolation_forest" in result.detail
        assert "n_features=42" in result.detail
