"""ENG-3d-2 — Isolation Forest training pipeline.

Trains a per-tenant/per-building Isolation Forest model and logs both the
model and the per-building scaler to MLflow as a single run artifact.

Architecture constraints
------------------------
- One model per tenant, one model per building.  Tenants are NEVER pooled.
- Training is always invoked through Temporal activities, never from apps/api.
- The scaler is fitted on training data and persisted alongside the model
  in the MLflow run so it is loaded together at serving time.
- contamination is configurable per building type via MLEnsembleConfig.
  Do NOT hardcode it here.

EMPIRICAL VALIDATION REQUIRED
------------------------------
The contamination parameter (default 5%) must be calibrated against the
COMBED golden fixture (ENG-6c) and real pilot data (GTM-2a) before
production deployment.  The current default is a starting point only.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from uuid import UUID

import mlflow
import mlflow.sklearn
import numpy as np
from sklearn.ensemble import IsolationForest

from models.feature_store.feature_set_v1 import FeatureSetV1
from services.ml_ensemble.config import MLEnsembleConfig
from services.ml_ensemble.feature_assembly import (
    assemble_feature_vector_matrix,
    collect_rule_ids,
)
from services.ml_ensemble.models import TrainingArtifact, TrainingRunResult
from services.ml_ensemble.scaler import BuildingScaler

logger = logging.getLogger(__name__)

# Sub-directory used for per-run MLflow artifact naming.
_ARTIFACT_MODEL_DIR = "isolation_forest"
_ARTIFACT_SCALER_DIR = "scaler"


class IsolationForestTrainer:
    """Per-tenant/per-building Isolation Forest training pipeline.

    Usage
    -----
    ::

        trainer = IsolationForestTrainer()
        result = trainer.train(
            tenant_id=UUID("..."),
            building_id=UUID("..."),
            building_type="office",
            features=feature_list,
            config=MLEnsembleConfig(),
            mlflow_tracking_uri="file:///tmp/mlruns",
            training_trigger="calendar",
        )
    """

    def train(
        self,
        tenant_id: UUID,
        building_id: UUID,
        features: list[FeatureSetV1],
        config: MLEnsembleConfig | None = None,
        building_type: str = "unknown",
        mlflow_tracking_uri: str = "",
        training_trigger: str = "calendar",
        run_tags: dict[str, str] | None = None,
    ) -> TrainingRunResult:
        """Train an Isolation Forest for a single (tenant, building) pair.

        Parameters
        ----------
        tenant_id, building_id:
            Scoping identifiers.  A misconfigured or buggy call that passes
            the wrong tenant_id cannot leak another tenant's features because
            the features list is already scoped at the call site (all rows have
            the same tenant_id from the RLS-enforced query upstream).
        features:
            List of FeatureSetV1 rows for this building's training window.
            Must contain at least 2 rows with low_data_quality=False.
        config:
            MLEnsembleConfig; defaults to standard configuration.
        building_type:
            Used to look up per-building-type contamination override.
        mlflow_tracking_uri:
            Where to log the MLflow run.  Empty string uses the current
            tracking URI already configured in the process environment.
        training_trigger:
            'calendar' | 'drift' | 'feedback_volume'
        run_tags:
            Additional MLflow tags to attach to the run.

        Returns
        -------
        TrainingRunResult
            References to the logged model and scaler artifacts.
        """
        cfg = config or MLEnsembleConfig()

        usable = [f for f in features if not f.low_data_quality]
        if len(usable) < 2:
            raise ValueError(
                f"IsolationForestTrainer requires at least 2 usable (low_data_quality=False) "
                f"feature rows; got {len(usable)} for "
                f"tenant={tenant_id} building={building_id}."
            )

        rule_ids = collect_rule_ids(usable)
        raw_matrix = np.array(assemble_feature_vector_matrix(usable, rule_ids), dtype=float)

        scaler = BuildingScaler(tenant_id=tenant_id, building_id=building_id, rule_ids=rule_ids)
        scaled_matrix = scaler.fit_transform(raw_matrix)

        contamination = cfg.contamination_for_building_type(building_type)
        model = IsolationForest(
            n_estimators=cfg.n_estimators,
            contamination=contamination,
            random_state=cfg.if_random_state,
        )
        model.fit(scaled_matrix)

        if_scores = model.decision_function(scaled_matrix)
        anomaly_rate = float(np.mean(if_scores < 0))

        if mlflow_tracking_uri:
            mlflow.set_tracking_uri(mlflow_tracking_uri)

        mlflow.set_experiment(cfg.mlflow_experiment_name)
        tags = {
            "tenant_id": str(tenant_id),
            "building_id": str(building_id),
            "model_type": "isolation_forest",
            "building_type": building_type,
            "trigger": training_trigger,
        }
        if run_tags:
            tags.update(run_tags)

        with mlflow.start_run(tags=tags) as run:
            mlflow.log_params(
                {
                    "contamination": contamination,
                    "n_estimators": cfg.n_estimators,
                    "random_state": cfg.if_random_state,
                    "rolling_window_hours": 168,
                    "n_training_samples": len(usable),
                    "n_rule_ids": len(rule_ids),
                    "building_type": building_type,
                }
            )
            mlflow.log_metrics(
                {
                    "train_anomaly_rate": anomaly_rate,
                    "n_features": raw_matrix.shape[1],
                }
            )
            mlflow.log_dict({"rule_ids": rule_ids}, "rule_ids.json")
            mlflow.sklearn.log_model(model, _ARTIFACT_MODEL_DIR)

            with tempfile.TemporaryDirectory() as tmp_dir:
                scaler_path = scaler.save(Path(tmp_dir))
                mlflow.log_artifact(str(scaler_path), _ARTIFACT_SCALER_DIR)

            run_id = run.info.run_id
            model_uri = mlflow.get_artifact_uri(_ARTIFACT_MODEL_DIR)
            scaler_uri = mlflow.get_artifact_uri(_ARTIFACT_SCALER_DIR)

            registered_version: str | None = None
            try:
                from models.registry.register import register_model_version

                registered_version = register_model_version(
                    run_id=run_id,
                    artifact_path=_ARTIFACT_MODEL_DIR,
                    tenant_id=tenant_id,
                    building_id=building_id,
                    model_type="isolation_forest",
                    artifact_uri=model_uri,
                )
            except Exception:
                # Registration is a Model Registry concern layered on top of
                # a successful training run -- a registry-side failure (e.g.
                # transient backend issue) must not fail training itself.
                # The run and its artifacts are already durably logged above.
                logger.exception(
                    "IsolationForest training succeeded but Model Registry "
                    "registration failed for tenant=%s building=%s run_id=%s",
                    tenant_id,
                    building_id,
                    run_id,
                )

        logger.info(
            "IsolationForest trained: tenant=%s building=%s samples=%d "
            "contamination=%.3f anomaly_rate=%.3f run_id=%s",
            tenant_id,
            building_id,
            len(usable),
            contamination,
            anomaly_rate,
            run_id,
        )

        return TrainingRunResult(
            tenant_id=tenant_id,
            building_id=building_id,
            model_type="isolation_forest",
            training_trigger=training_trigger,
            mlflow_run_id=run_id,
            model_artifact=TrainingArtifact(
                run_id=run_id,
                artifact_path=_ARTIFACT_MODEL_DIR,
                artifact_uri=model_uri,
            ),
            scaler_artifact=TrainingArtifact(
                run_id=run_id,
                artifact_path=_ARTIFACT_SCALER_DIR,
                artifact_uri=scaler_uri,
            ),
            rule_ids_used=rule_ids,
            n_training_samples=len(usable),
            metrics={
                "train_anomaly_rate": anomaly_rate,
                "n_features": float(raw_matrix.shape[1]),
                "contamination": contamination,
            },
            registered_version=registered_version,
        )
