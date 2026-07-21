"""Unit-level coverage of train_and_evaluate()'s orchestration logic
(skip-on-insufficient-data, promote-on-approval, hold-on-rejection) via
dependency injection (promotion_gate/registry are already constructor
params) plus patching the DB/trainer boundaries -- a real end-to-end run
needs a live Postgres for FeatureStoreRepository and is exercised instead
by tests/e2e/test_training_pipeline_e2e.py (ENG-6e).
"""

from __future__ import annotations

import contextlib
import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from models.evaluation.promotion_gate import PromotionDecision
from models.feature_store.feature_set_v1 import FeatureSetV1
from pipelines.training.train_and_evaluate import train_and_evaluate
from services.ml_ensemble.models import TrainingArtifact, TrainingRunResult


def _make_features(n: int, tenant_id, circuit_id) -> list[FeatureSetV1]:  # noqa: ANN001
    start = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    return [
        FeatureSetV1(
            tenant_id=tenant_id,
            circuit_id=circuit_id,
            ts=start + datetime.timedelta(hours=i),
            day_type="business_day",
        )
        for i in range(n)
    ]


def _make_result(model_type: str, tenant_id, building_id) -> TrainingRunResult:  # noqa: ANN001
    artifact = TrainingArtifact(run_id="r1", artifact_path=model_type, artifact_uri="uri")
    return TrainingRunResult(
        tenant_id=tenant_id,
        building_id=building_id,
        model_type=model_type,
        mlflow_run_id="r1",
        model_artifact=artifact,
        scaler_artifact=artifact,
        n_training_samples=10,
        metrics={"train_anomaly_rate": 0.05},
        registered_version="1",
    )


@contextlib.asynccontextmanager
async def _noop_tenant_scope(session, tenant_id):  # noqa: ANN001
    yield session


class _FakeSessionCtx:
    async def __aenter__(self):  # noqa: ANN204
        return AsyncMock()

    async def __aexit__(self, *args):  # noqa: ANN204
        return False


@pytest.mark.unit
class TestTrainAndEvaluate:
    @pytest.mark.asyncio
    async def test_skips_when_too_few_usable_features(self) -> None:
        tenant_id, building_id, circuit_id = uuid4(), uuid4(), uuid4()

        with (
            patch(
                "pipelines.training.train_and_evaluate.get_session_factory",
                return_value=lambda: _FakeSessionCtx(),
            ),
            patch("pipelines.training.train_and_evaluate.tenant_scope", _noop_tenant_scope),
            patch("pipelines.training.train_and_evaluate.FeatureStoreRepository") as mock_repo_cls,
        ):
            mock_repo_cls.return_value.get_features_for_building = AsyncMock(
                return_value=_make_features(1, tenant_id, circuit_id)
            )
            summary = await train_and_evaluate(tenant_id, building_id)

        assert summary.skipped_reason is not None
        assert summary.outcomes == []

    @pytest.mark.asyncio
    async def test_promotes_when_gate_approves(self) -> None:
        tenant_id, building_id, circuit_id = uuid4(), uuid4(), uuid4()
        features = _make_features(20, tenant_id, circuit_id)

        gate = AsyncMock()
        gate.evaluate.return_value = PromotionDecision(approved=True, reason="ok")
        registry = MagicMock()

        with (
            patch(
                "pipelines.training.train_and_evaluate.get_session_factory",
                return_value=lambda: _FakeSessionCtx(),
            ),
            patch("pipelines.training.train_and_evaluate.tenant_scope", _noop_tenant_scope),
            patch("pipelines.training.train_and_evaluate.FeatureStoreRepository") as mock_repo_cls,
            patch("pipelines.training.train_and_evaluate.IsolationForestTrainer") as mock_if_cls,
            patch("pipelines.training.train_and_evaluate.AutoencoderTrainer") as mock_ae_cls,
        ):
            mock_repo_cls.return_value.get_features_for_building = AsyncMock(return_value=features)
            mock_if_cls.return_value.train.return_value = _make_result(
                "isolation_forest", tenant_id, building_id
            )
            mock_ae_cls.return_value.train.return_value = _make_result(
                "autoencoder", tenant_id, building_id
            )

            summary = await train_and_evaluate(
                tenant_id, building_id, promotion_gate=gate, registry=registry
            )

        assert summary.skipped_reason is None
        assert len(summary.outcomes) == 2
        assert all(o.decision.approved for o in summary.outcomes)
        assert registry.promote.call_count == 2

    @pytest.mark.asyncio
    async def test_does_not_promote_when_gate_rejects(self) -> None:
        tenant_id, building_id, circuit_id = uuid4(), uuid4(), uuid4()
        features = _make_features(20, tenant_id, circuit_id)

        gate = AsyncMock()
        gate.evaluate.return_value = PromotionDecision(approved=False, reason="rejected")
        registry = MagicMock()

        with (
            patch(
                "pipelines.training.train_and_evaluate.get_session_factory",
                return_value=lambda: _FakeSessionCtx(),
            ),
            patch("pipelines.training.train_and_evaluate.tenant_scope", _noop_tenant_scope),
            patch("pipelines.training.train_and_evaluate.FeatureStoreRepository") as mock_repo_cls,
            patch("pipelines.training.train_and_evaluate.IsolationForestTrainer") as mock_if_cls,
            patch("pipelines.training.train_and_evaluate.AutoencoderTrainer") as mock_ae_cls,
        ):
            mock_repo_cls.return_value.get_features_for_building = AsyncMock(return_value=features)
            mock_if_cls.return_value.train.return_value = _make_result(
                "isolation_forest", tenant_id, building_id
            )
            mock_ae_cls.return_value.train.return_value = _make_result(
                "autoencoder", tenant_id, building_id
            )

            summary = await train_and_evaluate(
                tenant_id, building_id, promotion_gate=gate, registry=registry
            )

        assert not any(o.decision.approved for o in summary.outcomes)
        registry.promote.assert_not_called()
