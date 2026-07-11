"""ENG-3d — Integration test: end-to-end ML Ensemble pipeline.

Tests the full pipeline:
    Golden Fixture → IsolationForestTrainer → MLflow (local FS)
    Golden Fixture → AutoencoderTrainer     → MLflow (local FS)
    Trained models → InMemoryModelRegistry → EnsembleServingService → EnsembleScoreRecord

All I/O uses local filesystem MLflow (file:///...).  No MLflow server required.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("torch", reason="PyTorch not installed; skip integration tests")

from models.serving.ensemble_serving import EnsembleServingService
from models.training.autoencoder import AutoencoderTrainer, _build_windows
from models.training.isolation_forest import IsolationForestTrainer
from services.ml_ensemble.config import MLEnsembleConfig
from services.ml_ensemble.feature_assembly import assemble_feature_vector_matrix, collect_rule_ids
from services.ml_ensemble.scaler import BuildingScaler
from tests.fixtures.ml_ensemble.golden_fixture import (
    make_global_outlier_features,
    make_normal_features,
    make_shape_anomaly_features,
    make_training_corpus,
)
from tests.unit.services.ml_ensemble.conftest import BUILDING, TENANT, InMemoryModelRegistry


@pytest.fixture()
def fast_cfg() -> MLEnsembleConfig:
    return MLEnsembleConfig(
        n_estimators=15,
        contamination=0.05,
        autoencoder_epochs=15,
        autoencoder_hidden_dims=[16, 8],
        autoencoder_latent_dim=4,
        window_length_hours=4,
        autoencoder_batch_size=16,
        autoencoder_reconstruction_threshold_percentile=90.0,
        ae_random_state=42,
        if_random_state=42,
    )


def test_full_pipeline_trains_and_scores(
    tmp_path: Path,
    fast_cfg: MLEnsembleConfig,
) -> None:
    """End-to-end: train IF + AE → register → score normal + anomalous features."""
    tracking_uri = f"sqlite:///{(tmp_path / 'mlflow.db').as_posix()}"
    corpus = make_training_corpus(n_normal_days=30)

    # Train Isolation Forest
    if_result = IsolationForestTrainer().train(
        tenant_id=TENANT,
        building_id=BUILDING,
        features=corpus,
        config=fast_cfg,
        mlflow_tracking_uri=tracking_uri,
    )
    assert if_result.mlflow_run_id != ""

    # Train Autoencoder
    ae_result = AutoencoderTrainer().train(
        tenant_id=TENANT,
        building_id=BUILDING,
        features=corpus,
        config=fast_cfg,
        mlflow_tracking_uri=tracking_uri,
    )
    assert ae_result.mlflow_run_id != ""

    # Build InMemoryModelRegistry with trained models
    rule_ids = if_result.rule_ids_used
    raw = np.array(assemble_feature_vector_matrix(corpus, rule_ids), dtype=float)

    # Reconstruct scaler for IF
    scaler_if = BuildingScaler(tenant_id=TENANT, building_id=BUILDING, rule_ids=rule_ids)
    scaler_if.fit(raw)

    # Reconstruct scaler for AE (same training data, same fit)
    scaler_ae = BuildingScaler(tenant_id=TENANT, building_id=BUILDING, rule_ids=rule_ids)
    scaler_ae.fit_transform(raw)

    import mlflow
    import mlflow.sklearn
    import torch

    from models.training.autoencoder import WindowAutoencoder

    mlflow.set_tracking_uri(tracking_uri)

    # Load IF model using run_id + artifact_path (works with all tracking backends)
    if_model_dir = mlflow.artifacts.download_artifacts(
        run_id=if_result.mlflow_run_id,
        artifact_path=if_result.model_artifact.artifact_path,
    )
    if_model = mlflow.sklearn.load_model(if_model_dir)

    # Load AE model from .pt checkpoint
    ae_dir = mlflow.artifacts.download_artifacts(
        run_id=ae_result.mlflow_run_id,
        artifact_path=ae_result.model_artifact.artifact_path,
    )
    pt_files = list(Path(ae_dir).glob("*.pt"))
    assert pt_files, "No .pt file found in AE artifact directory"
    ckpt = torch.load(pt_files[0], weights_only=False)
    ae = WindowAutoencoder(
        input_dim=ckpt["input_dim"],
        hidden_dims=ckpt["hidden_dims"],
        latent_dim=ckpt["latent_dim"],
        reconstruction_threshold=ckpt["reconstruction_threshold"],
    )
    ae.module.load_state_dict(ckpt["state_dict"])
    ae.module.eval()

    registry = InMemoryModelRegistry()
    registry.register_isolation_forest(TENANT, BUILDING, if_model, scaler_if._scaler, rule_ids)
    registry.register_autoencoder(TENANT, BUILDING, ae, scaler_ae._scaler, rule_ids)

    # Score normal features
    svc = EnsembleServingService(registry=registry)
    normal = make_normal_features(n_days=2)
    records = svc.score(TENANT, BUILDING, normal, window_length_hours=fast_cfg.window_length_hours)
    assert len(records) == len(normal)
    has_if = [r for r in records if r.if_score is not None]
    has_ae = [r for r in records if r.ae_reconstruction_error is not None]
    assert len(has_if) > 0, "Expected IF scores in some records"
    assert len(has_ae) > 0, "Expected AE scores in some records"

    # Score anomalous features
    outliers = make_global_outlier_features(n_outliers=5)
    outlier_records = svc.score(
        TENANT, BUILDING, outliers, window_length_hours=fast_cfg.window_length_hours
    )
    assert len(outlier_records) == len(outliers)

    shapes = make_shape_anomaly_features(n_days=3)
    shape_records = svc.score(
        TENANT, BUILDING, shapes, window_length_hours=fast_cfg.window_length_hours
    )
    assert len(shape_records) == len(shapes)

    # ensemble_is_anomalous must be True when either model flags
    for r in outlier_records:
        if r.if_score is not None and r.if_is_anomalous:
            assert r.ensemble_is_anomalous is True


def test_scaler_travels_with_model(
    tmp_path: Path,
    fast_cfg: MLEnsembleConfig,
) -> None:
    """Verify scaler artifact is in the same MLflow run as the IF model."""
    tracking_uri = f"sqlite:///{(tmp_path / 'mlflow.db').as_posix()}"
    corpus = make_training_corpus(n_normal_days=30)
    result = IsolationForestTrainer().train(
        tenant_id=TENANT,
        building_id=BUILDING,
        features=corpus,
        config=fast_cfg,
        mlflow_tracking_uri=tracking_uri,
    )
    assert result.model_artifact.run_id == result.scaler_artifact.run_id
    assert result.scaler_artifact.artifact_uri != ""


def test_ae_scaler_travels_with_ae_model(
    tmp_path: Path,
    fast_cfg: MLEnsembleConfig,
) -> None:
    """Verify AE scaler artifact is in the same MLflow run as the AE model."""
    tracking_uri = f"sqlite:///{(tmp_path / 'mlflow.db').as_posix()}"
    corpus = make_training_corpus(n_normal_days=30)
    result = AutoencoderTrainer().train(
        tenant_id=TENANT,
        building_id=BUILDING,
        features=corpus,
        config=fast_cfg,
        mlflow_tracking_uri=tracking_uri,
    )
    assert result.model_artifact.run_id == result.scaler_artifact.run_id
    assert result.scaler_artifact.artifact_uri != ""


def test_serving_latency_budget(fast_cfg: MLEnsembleConfig) -> None:
    """ENG-3d-4 DoD: serving must not threaten the < 5-min analysis pipeline budget (TRD §9.1).

    Scores 504 feature rows (21 days × 24 h — a realistic per-building batch) through
    both models and asserts completion within 30 seconds.  30 s is a conservative
    per-component allocation that comfortably fits inside the 5-minute full-pipeline
    target from TRD §9.1 even when other pipeline stages consume their own budget.

    Uses InMemoryModelRegistry so MLflow I/O does not inflate the timing.
    """
    import time

    from sklearn.ensemble import IsolationForest

    from models.training.autoencoder import WindowAutoencoder

    # Build trained models directly (avoid MLflow I/O — we are timing serving, not training)
    corpus = make_training_corpus(n_normal_days=30)
    rule_ids = collect_rule_ids(corpus)
    raw = np.array(assemble_feature_vector_matrix(corpus, rule_ids), dtype=float)

    scaler_if = BuildingScaler(tenant_id=TENANT, building_id=BUILDING, rule_ids=rule_ids)
    scaled_if = scaler_if.fit_transform(raw)
    if_model = IsolationForest(
        n_estimators=fast_cfg.n_estimators,
        contamination=fast_cfg.contamination,
        random_state=fast_cfg.if_random_state,
    )
    if_model.fit(scaled_if)

    scaler_ae = BuildingScaler(tenant_id=TENANT, building_id=BUILDING, rule_ids=rule_ids)
    scaled_ae = scaler_ae.fit_transform(raw)
    windows = _build_windows(scaled_ae, fast_cfg.window_length_hours)
    ae = WindowAutoencoder(
        input_dim=windows.shape[1],
        hidden_dims=list(fast_cfg.autoencoder_hidden_dims),
        latent_dim=fast_cfg.autoencoder_latent_dim,
    )
    AutoencoderTrainer._train_loop(ae, windows, fast_cfg)
    train_errors = ae.reconstruct(windows)
    ae.reconstruction_threshold = float(
        np.percentile(train_errors, fast_cfg.autoencoder_reconstruction_threshold_percentile)
    )

    registry = InMemoryModelRegistry()
    registry.register_isolation_forest(TENANT, BUILDING, if_model, scaler_if._scaler, rule_ids)
    registry.register_autoencoder(TENANT, BUILDING, ae, scaler_ae._scaler, rule_ids)

    # 21 days × 24 h = 504 feature rows — realistic per-building scoring batch
    features = make_normal_features(n_days=21)
    assert len(features) == 504

    svc = EnsembleServingService(registry=registry)
    t0 = time.monotonic()
    records = svc.score(
        TENANT, BUILDING, features, window_length_hours=fast_cfg.window_length_hours
    )
    elapsed = time.monotonic() - t0

    assert len(records) == len(features)
    assert elapsed < 30.0, (
        f"Serving {len(features)} features took {elapsed:.2f}s — "
        "must complete within 30s to satisfy the TRD §9.1 < 5-min pipeline budget."
    )
