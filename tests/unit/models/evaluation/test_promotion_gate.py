from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from models.evaluation.promotion_gate import PromotionGate, PromotionGateSettings
from services.ml_ensemble.models import TrainingArtifact, TrainingRunResult


def _session_with_promotion_count(n: int) -> AsyncMock:
    session = AsyncMock()
    result = AsyncMock()
    result.fetchone = lambda: SimpleNamespace(n=n)
    session.execute.return_value = result
    return session


def _make_result(
    n_training_samples: int = 100,
    anomaly_rate: float = 0.05,
    registered_version: str | None = "1",
) -> TrainingRunResult:
    tenant_id, building_id = uuid4(), uuid4()
    artifact = TrainingArtifact(run_id="run1", artifact_path="isolation_forest", artifact_uri="uri")
    return TrainingRunResult(
        tenant_id=tenant_id,
        building_id=building_id,
        model_type="isolation_forest",
        mlflow_run_id="run1",
        model_artifact=artifact,
        scaler_artifact=artifact,
        n_training_samples=n_training_samples,
        metrics={"train_anomaly_rate": anomaly_rate},
        registered_version=registered_version,
    )


@pytest.mark.unit
class TestPromotionGate:
    @pytest.mark.asyncio
    async def test_rejects_when_registration_failed(self) -> None:
        gate = PromotionGate()
        session = _session_with_promotion_count(0)
        result = _make_result(registered_version=None)

        decision = await gate.evaluate(session, result)

        assert decision.approved is False
        assert "registration" in decision.reason.lower()

    @pytest.mark.asyncio
    async def test_rejects_when_too_few_training_samples(self) -> None:
        settings = PromotionGateSettings(min_training_samples=50)
        gate = PromotionGate(settings)
        session = _session_with_promotion_count(0)
        result = _make_result(n_training_samples=10)

        decision = await gate.evaluate(session, result)

        assert decision.approved is False
        assert "samples" in decision.reason.lower()

    @pytest.mark.asyncio
    async def test_rejects_when_anomaly_rate_exceeds_sanity_bound(self) -> None:
        settings = PromotionGateSettings(max_reasonable_anomaly_rate=0.25)
        gate = PromotionGate(settings)
        session = _session_with_promotion_count(0)
        result = _make_result(anomaly_rate=0.9)

        decision = await gate.evaluate(session, result)

        assert decision.approved is False
        assert "anomaly_rate" in decision.reason.lower()

    @pytest.mark.asyncio
    async def test_requires_human_review_for_first_n_promotions(self) -> None:
        settings = PromotionGateSettings(human_review_required_first_n_promotions=3)
        gate = PromotionGate(settings)
        session = _session_with_promotion_count(1)  # this would be the 2nd promotion
        result = _make_result()

        decision = await gate.evaluate(session, result)

        assert decision.requires_human_review is True
        assert decision.approved is False

    @pytest.mark.asyncio
    async def test_auto_approves_after_review_threshold(self) -> None:
        settings = PromotionGateSettings(human_review_required_first_n_promotions=3)
        gate = PromotionGate(settings)
        session = _session_with_promotion_count(5)  # past the review threshold
        result = _make_result()

        decision = await gate.evaluate(session, result)

        assert decision.requires_human_review is False
        assert decision.approved is True

    @pytest.mark.asyncio
    async def test_every_decision_writes_an_audit_log_entry(self) -> None:
        gate = PromotionGate(PromotionGateSettings(human_review_required_first_n_promotions=0))
        session = _session_with_promotion_count(0)
        result = _make_result()

        await gate.evaluate(session, result)

        # count_promotions (SELECT) + log_model_event (INSERT) = 2 calls
        assert session.execute.await_count == 2
