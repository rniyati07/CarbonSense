"""ENG-6a (ROADMAP ENG-6a) — MLflowModelRegistry: the real Model Registry-
backed ModelRegistryProtocol implementation that models/serving/
local_registry.py's own module docstring has been waiting on since ENG-3d.

LocalModelRegistry resolves "the model to serve" as *the most recent
training run* (an MLflow tag search, no promotion concept). That was
always an approximation standing in for the real thing: TRD v2.0 §6.1
requires a *promoted* version, evaluated in shadow mode before serving
sees it (§6.3) -- training a new candidate must not silently start
serving it. MLflowModelRegistry resolves "the model to serve" as the
version carrying the "champion" registry alias, which nothing sets except
the promotion gate (models/evaluation/promotion_gate.py, ENG-6c) after a
candidate passes evaluation. Until a first promotion happens for a given
(tenant, building, model_type), no version carries the alias and
load_isolation_forest()/load_autoencoder() raise ModelNotRegisteredError
-- the same "nothing promoted yet" cold-start case LocalModelRegistry
already had to handle.

Uses MLflow's alias-based promotion API (`set_registered_model_alias` /
`get_model_version_by_alias`), not the `stage=` API -- stages were removed
in MLflow 2.9+ and this repo runs MLflow 3.x (see shared/config/ml_registry.py
for the required database-backed tracking store the Model Registry API
needs; a plain filesystem store cannot back a registry at all).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

import mlflow
import mlflow.artifacts
import mlflow.sklearn
from mlflow import MlflowClient
from mlflow.exceptions import MlflowException

from models.registry.register import registered_model_name
from models.serving.local_registry import ModelNotRegisteredError
from services.ml_ensemble.scaler import BuildingScaler

if TYPE_CHECKING:
    from sklearn.ensemble import IsolationForest
    from sklearn.preprocessing import StandardScaler

    from models.training.autoencoder import WindowAutoencoder
    from services.ml_ensemble.models import TrainingRunResult

logger = logging.getLogger(__name__)

CHAMPION_ALIAS = "champion"

_ISOLATION_FOREST_ARTIFACT_DIR = "isolation_forest"
_AUTOENCODER_ARTIFACT_DIR = "autoencoder"
_SCALER_ARTIFACT_DIR = "scaler"
_RULE_IDS_ARTIFACT = "rule_ids.json"


class MLflowModelRegistry:
    """Implements ModelRegistryProtocol against MLflow's real Model
    Registry (registered models + version aliases), not just the
    tracking-store run search LocalModelRegistry uses."""

    def __init__(self, tracking_uri: str | None = None) -> None:
        if tracking_uri is None:
            from shared.config.ml_registry import LocalModelRegistrySettings

            tracking_uri = LocalModelRegistrySettings().tracking_uri
        mlflow.set_tracking_uri(tracking_uri)
        self._tracking_uri = tracking_uri
        self._client = MlflowClient(tracking_uri=tracking_uri)

    @property
    def tracking_uri(self) -> str:
        return self._tracking_uri

    def save_training_result(self, result: TrainingRunResult) -> None:
        """No-op -- see LocalModelRegistry.save_training_result's identical
        rationale. Registration itself (a *separate* step from logging)
        happens inside the trainers via models.registry.register, not here."""
        logger.debug(
            "save_training_result: no-op; run_id=%s tenant=%s building=%s model_type=%s "
            "registered_version=%s",
            result.mlflow_run_id,
            result.tenant_id,
            result.building_id,
            result.model_type,
            result.registered_version,
        )

    def promote(self, tenant_id: UUID, building_id: UUID, model_type: str, version: str) -> None:
        """Set `version` as the champion for (tenant, building, model_type).
        Called by the promotion gate (ENG-6c) after a candidate passes
        shadow-mode evaluation -- never called directly by training code,
        which only registers a version without promoting it (TRD v2.0
        §6.3: a retrained candidate is evaluated before promotion, not
        served automatically on training completion)."""
        name = registered_model_name(tenant_id, building_id, model_type)
        self._client.set_registered_model_alias(name, CHAMPION_ALIAS, version)
        logger.info("promote: %s@%s -> version %s", name, CHAMPION_ALIAS, version)

    def get_champion_version(
        self, tenant_id: UUID, building_id: UUID, model_type: str
    ) -> str | None:
        """The currently-promoted version number, or None if nothing has
        been promoted yet for this (tenant, building, model_type)."""
        name = registered_model_name(tenant_id, building_id, model_type)
        try:
            return str(self._client.get_model_version_by_alias(name, CHAMPION_ALIAS).version)
        except MlflowException:
            return None

    def get_previous_version(
        self, tenant_id: UUID, building_id: UUID, model_type: str
    ) -> str | None:
        """The registered version immediately older than the current
        champion -- the rollback target (ENG-6d, TRD v2.0 §6.4: "the
        registry retains the last K promoted versions... in a
        hot-swappable state"). None if there's no champion, or the
        champion is already the oldest registered version."""
        name = registered_model_name(tenant_id, building_id, model_type)
        current = self.get_champion_version(tenant_id, building_id, model_type)
        if current is None:
            return None

        versions = sorted(
            (int(mv.version) for mv in self._client.search_model_versions(f"name='{name}'")),
            reverse=True,
        )
        older = [v for v in versions if v < int(current)]
        return str(older[0]) if older else None

    def load_isolation_forest(
        self,
        tenant_id: UUID,
        building_id: UUID,
    ) -> tuple[IsolationForest, StandardScaler, list[str]]:
        run_id = self._champion_run_id(tenant_id, building_id, "isolation_forest")
        model = mlflow.sklearn.load_model(f"runs:/{run_id}/{_ISOLATION_FOREST_ARTIFACT_DIR}")
        scaler = self._load_scaler(run_id)
        rule_ids = self._load_rule_ids(run_id)
        return model, scaler, rule_ids

    def load_autoencoder(
        self,
        tenant_id: UUID,
        building_id: UUID,
    ) -> tuple[WindowAutoencoder, StandardScaler, list[str]]:
        import torch

        from models.training.autoencoder import WindowAutoencoder

        run_id = self._champion_run_id(tenant_id, building_id, "autoencoder")
        local_dir = mlflow.artifacts.download_artifacts(
            run_id=run_id, artifact_path=_AUTOENCODER_ARTIFACT_DIR
        )
        checkpoint: dict[str, Any] = torch.load(
            Path(local_dir) / "autoencoder.pt", weights_only=False
        )
        ae = WindowAutoencoder(
            input_dim=checkpoint["input_dim"],
            hidden_dims=checkpoint["hidden_dims"],
            latent_dim=checkpoint["latent_dim"],
            reconstruction_threshold=checkpoint.get("reconstruction_threshold", float("inf")),
        )
        ae.module.load_state_dict(checkpoint["state_dict"])
        ae.module.eval()

        scaler = self._load_scaler(run_id)
        rule_ids = self._load_rule_ids(run_id)
        return ae, scaler, rule_ids

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _champion_run_id(self, tenant_id: UUID, building_id: UUID, model_type: str) -> str:
        name = registered_model_name(tenant_id, building_id, model_type)
        try:
            version = self._client.get_model_version_by_alias(name, CHAMPION_ALIAS)
        except MlflowException as exc:
            raise ModelNotRegisteredError(
                f"No promoted ({CHAMPION_ALIAS!r}) {model_type} version for "
                f"tenant={tenant_id} building={building_id}"
            ) from exc
        return str(version.run_id)

    def _load_scaler(self, run_id: str) -> BuildingScaler:
        local_dir = mlflow.artifacts.download_artifacts(
            run_id=run_id, artifact_path=_SCALER_ARTIFACT_DIR
        )
        return BuildingScaler.load(Path(local_dir) / BuildingScaler.SCALER_FILE)

    def _load_rule_ids(self, run_id: str) -> list[str]:
        data = mlflow.artifacts.load_dict(f"runs:/{run_id}/{_RULE_IDS_ARTIFACT}")
        return list(data.get("rule_ids", []))
