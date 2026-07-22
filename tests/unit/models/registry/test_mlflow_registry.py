"""End-to-end against a real sqlite-backed MLflow tracking store: train a
real model via the real trainer (which now registers a version as part of
training, ENG-6a), confirm it is NOT loadable until explicitly promoted
(TRD v2.0 §6.3: a candidate must not silently start serving), then confirm
promotion, reload, and rollback-target resolution all work against real
MLflow Model Registry state -- not mocks, matching the same real-registry
testing pattern tests/unit/models/serving/test_local_registry.py already
established for LocalModelRegistry.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest

from models.registry.mlflow_registry import MLflowModelRegistry
from models.serving.local_registry import ModelNotRegisteredError
from models.training.isolation_forest import IsolationForestTrainer
from services.ml_ensemble.feature_assembly import assemble_feature_vector_matrix
from tests.fixtures.ml_ensemble.golden_fixture import make_training_corpus


@pytest.fixture()
def tracking_uri() -> str:
    db_path = Path(tempfile.mkdtemp()) / "mlflow.db"
    return f"sqlite:///{db_path.as_posix()}"


@pytest.fixture()
def registry(tracking_uri: str) -> MLflowModelRegistry:
    return MLflowModelRegistry(tracking_uri=tracking_uri)


@pytest.mark.unit
class TestMLflowModelRegistryLifecycle:
    def test_trained_but_unpromoted_model_is_not_loadable(
        self, registry: MLflowModelRegistry, tracking_uri: str
    ) -> None:
        tenant_id, building_id = uuid4(), uuid4()
        corpus = make_training_corpus(n_normal_days=10)

        trainer = IsolationForestTrainer()
        result = trainer.train(
            tenant_id=tenant_id,
            building_id=building_id,
            features=corpus,
            building_type="office",
            mlflow_tracking_uri=tracking_uri,
        )

        assert result.registered_version is not None
        assert registry.get_champion_version(tenant_id, building_id, "isolation_forest") is None
        with pytest.raises(ModelNotRegisteredError):
            registry.load_isolation_forest(tenant_id, building_id)

    def test_promote_then_load_produces_real_scores(
        self, registry: MLflowModelRegistry, tracking_uri: str
    ) -> None:
        tenant_id, building_id = uuid4(), uuid4()
        corpus = make_training_corpus(n_normal_days=10)

        trainer = IsolationForestTrainer()
        result = trainer.train(
            tenant_id=tenant_id,
            building_id=building_id,
            features=corpus,
            building_type="office",
            mlflow_tracking_uri=tracking_uri,
        )
        assert result.registered_version is not None

        registry.promote(tenant_id, building_id, "isolation_forest", result.registered_version)
        assert (
            registry.get_champion_version(tenant_id, building_id, "isolation_forest")
            == result.registered_version
        )

        model, scaler, rule_ids = registry.load_isolation_forest(tenant_id, building_id)
        raw = np.array(assemble_feature_vector_matrix(corpus[:5], rule_ids), dtype=float)
        scores = model.decision_function(scaler.transform(raw))
        assert scores.shape == (5,)
        assert np.isfinite(scores).all()

    def test_retrain_then_promote_updates_champion_and_prior_version(
        self, registry: MLflowModelRegistry, tracking_uri: str
    ) -> None:
        tenant_id, building_id = uuid4(), uuid4()
        corpus = make_training_corpus(n_normal_days=10)
        trainer = IsolationForestTrainer()

        result_v1 = trainer.train(
            tenant_id=tenant_id,
            building_id=building_id,
            features=corpus,
            building_type="office",
            mlflow_tracking_uri=tracking_uri,
        )
        assert result_v1.registered_version is not None
        registry.promote(tenant_id, building_id, "isolation_forest", result_v1.registered_version)

        result_v2 = trainer.train(
            tenant_id=tenant_id,
            building_id=building_id,
            features=corpus,
            building_type="office",
            mlflow_tracking_uri=tracking_uri,
            training_trigger="drift",
        )
        assert result_v2.registered_version != result_v1.registered_version
        assert result_v2.registered_version is not None
        registry.promote(tenant_id, building_id, "isolation_forest", result_v2.registered_version)

        assert (
            registry.get_champion_version(tenant_id, building_id, "isolation_forest")
            == result_v2.registered_version
        )
        assert (
            registry.get_previous_version(tenant_id, building_id, "isolation_forest")
            == result_v1.registered_version
        )

    def test_get_previous_version_is_none_with_only_one_promotion(
        self, registry: MLflowModelRegistry, tracking_uri: str
    ) -> None:
        tenant_id, building_id = uuid4(), uuid4()
        corpus = make_training_corpus(n_normal_days=10)
        trainer = IsolationForestTrainer()

        result = trainer.train(
            tenant_id=tenant_id,
            building_id=building_id,
            features=corpus,
            building_type="office",
            mlflow_tracking_uri=tracking_uri,
        )
        assert result.registered_version is not None
        registry.promote(tenant_id, building_id, "isolation_forest", result.registered_version)

        assert registry.get_previous_version(tenant_id, building_id, "isolation_forest") is None

    def test_get_champion_version_none_for_unknown_building(
        self, registry: MLflowModelRegistry
    ) -> None:
        assert registry.get_champion_version(uuid4(), uuid4(), "isolation_forest") is None
