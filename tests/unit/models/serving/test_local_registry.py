"""Formalizes the manual end-to-end smoke test run during design: train a
real model via the real trainer, load it back through LocalModelRegistry,
and confirm it produces real scores -- not just that the classes import.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest

from models.serving.local_registry import LocalModelRegistry, ModelNotRegisteredError
from models.training.isolation_forest import IsolationForestTrainer
from services.ml_ensemble.feature_assembly import assemble_feature_vector_matrix
from tests.fixtures.ml_ensemble.golden_fixture import make_training_corpus


@pytest.fixture()
def tracking_uri() -> str:
    db_path = Path(tempfile.mkdtemp()) / "mlflow.db"
    return f"sqlite:///{db_path.as_posix()}"


@pytest.fixture()
def registry(tracking_uri: str) -> LocalModelRegistry:
    return LocalModelRegistry(tracking_uri=tracking_uri)


class TestLocalModelRegistryIsolationForest:
    def test_train_then_load_produces_real_scores(
        self, registry: LocalModelRegistry, tracking_uri: str
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
        assert result.mlflow_run_id

        model, scaler, rule_ids = registry.load_isolation_forest(tenant_id, building_id)

        raw = np.array(assemble_feature_vector_matrix(corpus[:5], rule_ids), dtype=float)
        scaled = scaler.transform(raw)
        scores = model.decision_function(scaled)

        assert scores.shape == (5,)
        assert np.isfinite(scores).all()

    def test_load_for_untrained_building_raises_model_not_registered(
        self, registry: LocalModelRegistry
    ) -> None:
        with pytest.raises(ModelNotRegisteredError):
            registry.load_isolation_forest(uuid4(), uuid4())

    def test_save_training_result_does_not_raise(
        self, registry: LocalModelRegistry, tracking_uri: str
    ) -> None:
        """save_training_result() is documented as a no-op (the training run's
        own mlflow logging already persisted everything) -- just needs to not
        blow up when called, matching how a training activity would call it."""
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

        registry.save_training_result(result)  # must not raise


class TestLocalModelRegistryAutoencoder:
    def test_train_then_load_produces_real_reconstruction(
        self, registry: LocalModelRegistry, tracking_uri: str
    ) -> None:
        pytest.importorskip("torch", reason="PyTorch not installed; skip autoencoder test")
        from models.training.autoencoder import AutoencoderTrainer
        from services.ml_ensemble.config import MLEnsembleConfig

        tenant_id, building_id = uuid4(), uuid4()
        corpus = make_training_corpus(n_normal_days=10)
        fast_config = MLEnsembleConfig(
            autoencoder_epochs=5,
            autoencoder_hidden_dims=[16, 8],
            autoencoder_latent_dim=4,
            window_length_hours=4,
            autoencoder_batch_size=16,
            ae_random_state=42,
            autoencoder_reconstruction_threshold_percentile=90.0,
        )

        trainer = AutoencoderTrainer()
        result = trainer.train(
            tenant_id=tenant_id,
            building_id=building_id,
            features=corpus,
            config=fast_config,
            mlflow_tracking_uri=tracking_uri,
        )
        assert result.mlflow_run_id

        ae, scaler, rule_ids = registry.load_autoencoder(tenant_id, building_id)

        from models.training.autoencoder import _build_windows

        raw = np.array(assemble_feature_vector_matrix(corpus, rule_ids), dtype=float)
        scaled = scaler.transform(raw)
        windows = _build_windows(scaled, fast_config.window_length_hours)

        errors = ae.reconstruct(windows)

        assert errors.shape[0] == windows.shape[0]
        assert np.isfinite(errors).all()
        assert (errors >= 0).all()

    def test_load_for_untrained_building_raises_model_not_registered(
        self, registry: LocalModelRegistry
    ) -> None:
        pytest.importorskip("torch", reason="PyTorch not installed; skip autoencoder test")
        with pytest.raises(ModelNotRegisteredError):
            registry.load_autoencoder(uuid4(), uuid4())
