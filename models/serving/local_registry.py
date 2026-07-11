"""ENG-2c-wiring / Phase 4 — LocalModelRegistry.

ModelRegistryProtocol has been waiting on ENG-6a ("Stand up MLflow model
registry with the models:/{tenant_id}/{building_id}/{layer}/{version} URI
convention", ROADMAP ENG-6a) since ENG-3d was built. This is NOT that --
ENG-6a's promotion gating (ENG-6c), rollback (ENG-6d), and the formal
`models:/` registered-model URI scheme remain unimplemented, as instructed.

What this IS: the training code in models/training/isolation_forest.py and
models/training/autoencoder.py already calls mlflow.start_run(tags={...
"tenant_id", "building_id", "model_type" ...}), mlflow.sklearn.log_model(),
and mlflow.log_artifact() for the scaler/rule_ids -- against MLflow's own
local file-based tracking store (./mlruns/, already present in this repo)
whenever MLFLOW_TRACKING_URI isn't set to a real server. That logging was
never in question; only the *lookup* side (ModelRegistryProtocol.
load_isolation_forest/load_autoencoder for a given tenant+building) was
missing. LocalModelRegistry supplies exactly that lookup, using MLflow's
own local search_runs API against the tags the training code already
writes -- no new serialization scheme invented, no artifact storage
duplicated.

Swapping to a real MLflowModelRegistry once ENG-6a lands is a one-line
dependency-injection change: both classes implement the identical
ModelRegistryProtocol; nothing that constructs a registry and passes it
to EnsembleServingService needs to change beyond which class it imports.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

import mlflow
import mlflow.artifacts
import mlflow.sklearn

from services.ml_ensemble.scaler import BuildingScaler

if TYPE_CHECKING:
    from sklearn.ensemble import IsolationForest
    from sklearn.preprocessing import StandardScaler

    from models.training.autoencoder import WindowAutoencoder
    from services.ml_ensemble.models import TrainingRunResult

logger = logging.getLogger(__name__)

_ISOLATION_FOREST_ARTIFACT_DIR = "isolation_forest"
_AUTOENCODER_ARTIFACT_DIR = "autoencoder"
_SCALER_ARTIFACT_DIR = "scaler"
_RULE_IDS_ARTIFACT = "rule_ids.json"


class ModelNotRegisteredError(Exception):
    """No completed training run found for this (tenant, building, model_type).

    Caught by EnsembleServingService's existing `except Exception` handling
    (models/serving/ensemble_serving.py) -- an untrained model degrades that
    scorer's output to None/False, matching TRD v2.0 2.4's cold-start
    reduced-confidence behavior. Not a new failure mode; the real
    MLflowModelRegistry (ENG-6a) will need to handle the identical "nothing
    promoted yet" case.
    """


class LocalModelRegistry:
    """Implements ModelRegistryProtocol against MLflow's local tracking store."""

    def __init__(self, tracking_uri: str | None = None) -> None:
        if tracking_uri:
            mlflow.set_tracking_uri(tracking_uri)
        self._tracking_uri = tracking_uri

    def save_training_result(self, result: TrainingRunResult) -> None:
        """No-op by design: the training code's own mlflow.start_run() +
        log_model()/log_artifact() calls (models/training/isolation_forest.py,
        autoencoder.py) already durably persisted everything this method
        would otherwise persist, before TrainingRunResult was even
        constructed. Re-writing it here would duplicate storage, not add
        anything. Logged at debug level so a caller relying on this method
        actually doing work is visible in logs rather than silently no-op'ing.
        """
        logger.debug(
            "save_training_result: no-op (already logged by the training run "
            "itself); run_id=%s tenant=%s building=%s model_type=%s",
            result.mlflow_run_id,
            result.tenant_id,
            result.building_id,
            result.model_type,
        )

    def load_isolation_forest(
        self,
        tenant_id: UUID,
        building_id: UUID,
    ) -> tuple[IsolationForest, StandardScaler, list[str]]:
        run_id = self._find_latest_run(tenant_id, building_id, "isolation_forest")
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

        run_id = self._find_latest_run(tenant_id, building_id, "autoencoder")
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

    def _find_latest_run(self, tenant_id: UUID, building_id: UUID, model_type: str) -> str:
        filter_string = (
            f"tags.tenant_id = '{tenant_id}' "
            f"and tags.building_id = '{building_id}' "
            f"and tags.model_type = '{model_type}'"
        )
        runs = mlflow.search_runs(
            filter_string=filter_string,
            order_by=["start_time DESC"],
            max_results=1,
            search_all_experiments=True,
        )
        if runs.empty:
            raise ModelNotRegisteredError(
                f"No {model_type} training run found for tenant={tenant_id} "
                f"building={building_id}"
            )
        return str(runs.iloc[0]["run_id"])

    def _load_scaler(self, run_id: str) -> BuildingScaler:
        local_dir = mlflow.artifacts.download_artifacts(
            run_id=run_id, artifact_path=_SCALER_ARTIFACT_DIR
        )
        return BuildingScaler.load(Path(local_dir) / BuildingScaler.SCALER_FILE)

    def _load_rule_ids(self, run_id: str) -> list[str]:
        data = mlflow.artifacts.load_dict(f"runs:/{run_id}/{_RULE_IDS_ARTIFACT}")
        return list(data.get("rule_ids", []))
