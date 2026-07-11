"""Shared fixtures for ENG-3d ML Ensemble unit tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from models.feature_store.feature_set_v1 import FeatureSetV1
from services.ml_ensemble.config import MLEnsembleConfig
from tests.fixtures.ml_ensemble.golden_fixture import (
    BUILDING_ID,
    CIRCUIT_ID,
    TENANT_ID,
    make_global_outlier_features,
    make_normal_features,
    make_shape_anomaly_features,
    make_training_corpus,
)

# ------------------------------------------------------------------ #
# Canonical IDs (re-exported for test use)
# ------------------------------------------------------------------ #

TENANT = TENANT_ID
BUILDING = BUILDING_ID
CIRCUIT = CIRCUIT_ID


# ------------------------------------------------------------------ #
# Config fixture — reduced epochs for fast tests
# ------------------------------------------------------------------ #


@pytest.fixture()
def fast_config() -> MLEnsembleConfig:
    """MLEnsembleConfig with minimal epochs/estimators for test speed."""
    return MLEnsembleConfig(
        n_estimators=10,
        autoencoder_epochs=5,
        autoencoder_hidden_dims=[16, 8],
        autoencoder_latent_dim=4,
        window_length_hours=4,
        autoencoder_batch_size=16,
        contamination=0.05,
    )


# ------------------------------------------------------------------ #
# Feature corpus fixtures
# ------------------------------------------------------------------ #


@pytest.fixture()
def normal_features() -> list[FeatureSetV1]:
    """30 days × 24 h of sinusoidal normal features."""
    return make_normal_features(n_days=30)


@pytest.fixture()
def training_corpus() -> list[FeatureSetV1]:
    """Clean training corpus — normal data only."""
    return make_training_corpus(n_normal_days=30)


@pytest.fixture()
def global_outlier_features() -> list[FeatureSetV1]:
    """Point anomalies with extreme kWh magnitude."""
    return make_global_outlier_features(n_outliers=5)


@pytest.fixture()
def shape_anomaly_features() -> list[FeatureSetV1]:
    """Inverted-pattern anomalies within normal magnitude range."""
    return make_shape_anomaly_features(n_days=2)


# ------------------------------------------------------------------ #
# MLflow tracking URI (local filesystem, no server required)
# ------------------------------------------------------------------ #


@pytest.fixture()
def mlflow_tracking_uri(tmp_path: Path) -> str:
    """SQLite-backed MLflow tracking URI for test isolation (no server required)."""
    db_path = tmp_path / "mlflow_test.db"
    return f"sqlite:///{db_path.as_posix()}"


# ------------------------------------------------------------------ #
# InMemoryModelRegistry — implements ModelRegistryProtocol for tests
# ------------------------------------------------------------------ #


class InMemoryModelRegistry:
    """Test double for ModelRegistryProtocol.

    Stores trained models and scalers in memory so tests don't need MLflow.
    """

    def __init__(self) -> None:
        self._if_store: dict[tuple[UUID, UUID], Any] = {}
        self._ae_store: dict[tuple[UUID, UUID], Any] = {}
        self._training_results: list[Any] = []

    def save_training_result(self, result: Any) -> None:
        self._training_results.append(result)

    def register_isolation_forest(
        self,
        tenant_id: UUID,
        building_id: UUID,
        model: Any,
        scaler: Any,
        rule_ids: list[str],
    ) -> None:
        self._if_store[(tenant_id, building_id)] = (model, scaler, rule_ids)

    def register_autoencoder(
        self,
        tenant_id: UUID,
        building_id: UUID,
        model: Any,
        scaler: Any,
        rule_ids: list[str],
    ) -> None:
        self._ae_store[(tenant_id, building_id)] = (model, scaler, rule_ids)

    def load_isolation_forest(
        self,
        tenant_id: UUID,
        building_id: UUID,
    ) -> tuple[Any, Any, list[str]]:
        key = (tenant_id, building_id)
        if key not in self._if_store:
            raise KeyError(f"No IF model for tenant={tenant_id} building={building_id}")
        return self._if_store[key]

    def load_autoencoder(
        self,
        tenant_id: UUID,
        building_id: UUID,
    ) -> tuple[Any, Any, list[str]]:
        key = (tenant_id, building_id)
        if key not in self._ae_store:
            raise KeyError(f"No AE model for tenant={tenant_id} building={building_id}")
        return self._ae_store[key]


@pytest.fixture()
def in_memory_registry() -> InMemoryModelRegistry:
    return InMemoryModelRegistry()
