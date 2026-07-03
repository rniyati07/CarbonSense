"""ENG-3d — Temporal activities for ML Ensemble training and inference.

These activities form the ONLY entry point from the Temporal orchestration
layer into the ML training pipelines.  They call into:
    - models/training/isolation_forest.py  (IsolationForestTrainer)
    - models/training/autoencoder.py       (AutoencoderTrainer)
    - models/serving/ensemble_serving.py   (EnsembleServingService)

Architecture constraints
------------------------
- Training pipelines (models/training/) are only reachable through these
  activities.  apps/api MUST NOT import models/training/ or call trainers directly.
- The activities are responsible for fetching feature data from the feature
  store and passing it to the trainers.  The trainers are stateless.
- Each activity targets a SINGLE (tenant, building) pair — no cross-tenant
  pooling is permitted at any layer.
"""

from __future__ import annotations

import logging
from uuid import UUID

from temporalio import activity

from orchestration.temporal.dto import MLTrainingInput, MLTrainingResult

logger = logging.getLogger(__name__)


@activity.defn
async def train_isolation_forest_activity(input: MLTrainingInput) -> MLTrainingResult:
    """Train an Isolation Forest for a single (tenant, building) pair.

    Fetches FeatureSetV1 rows from the feature store, trains the IF pipeline,
    and logs the model + scaler to MLflow.

    Parameters
    ----------
    input:
        MLTrainingInput with tenant_id, building_id, building_type, trigger,
        and optional mlflow_tracking_uri.

    Returns
    -------
    MLTrainingResult
        MLflow run_id, model artifact URI, scaler artifact URI, sample count.
    """
    activity.heartbeat()

    tenant_id = UUID(input.tenant_id)
    building_id = UUID(input.building_id)

    logger.info(
        "train_isolation_forest_activity: start tenant=%s building=%s trigger=%s",
        input.tenant_id,
        input.building_id,
        input.trigger,
    )

    activity.heartbeat()

    features = await _fetch_training_features(tenant_id, building_id)
    if not features:
        logger.warning(
            "train_isolation_forest_activity: no features for tenant=%s building=%s — skipping",
            input.tenant_id,
            input.building_id,
        )
        return MLTrainingResult(
            tenant_id=input.tenant_id,
            building_id=input.building_id,
            model_type="isolation_forest",
            mlflow_run_id="",
            model_artifact_uri="",
            scaler_artifact_uri="",
            n_training_samples=0,
            status="skipped",
            detail="No usable training features available.",
        )

    activity.heartbeat()

    from models.training.isolation_forest import IsolationForestTrainer
    from services.ml_ensemble.config import MLEnsembleConfig

    trainer = IsolationForestTrainer()
    result = trainer.train(
        tenant_id=tenant_id,
        building_id=building_id,
        features=features,
        config=MLEnsembleConfig(),
        building_type=input.building_type,
        mlflow_tracking_uri=input.mlflow_tracking_uri,
        training_trigger=input.trigger,
    )

    logger.info(
        "train_isolation_forest_activity: complete tenant=%s building=%s run_id=%s samples=%d",
        input.tenant_id,
        input.building_id,
        result.mlflow_run_id,
        result.n_training_samples,
    )

    return MLTrainingResult(
        tenant_id=input.tenant_id,
        building_id=input.building_id,
        model_type="isolation_forest",
        mlflow_run_id=result.mlflow_run_id,
        model_artifact_uri=result.model_artifact.artifact_uri,
        scaler_artifact_uri=result.scaler_artifact.artifact_uri,
        n_training_samples=result.n_training_samples,
        status="completed",
    )


@activity.defn
async def train_autoencoder_activity(input: MLTrainingInput) -> MLTrainingResult:
    """Train a Windowed Autoencoder for a single (tenant, building) pair.

    Fetches FeatureSetV1 rows from the feature store, trains the AE pipeline,
    and logs the model + scaler to MLflow.

    Parameters
    ----------
    input:
        MLTrainingInput with tenant_id, building_id, trigger, and optional
        mlflow_tracking_uri.  building_type is not used by AE (no per-type
        contamination override — that is IF-specific).

    Returns
    -------
    MLTrainingResult
        MLflow run_id, model artifact URI, scaler artifact URI, sample count.
    """
    activity.heartbeat()

    tenant_id = UUID(input.tenant_id)
    building_id = UUID(input.building_id)

    logger.info(
        "train_autoencoder_activity: start tenant=%s building=%s trigger=%s",
        input.tenant_id,
        input.building_id,
        input.trigger,
    )

    activity.heartbeat()

    features = await _fetch_training_features(tenant_id, building_id)
    if not features:
        logger.warning(
            "train_autoencoder_activity: no features for tenant=%s building=%s — skipping",
            input.tenant_id,
            input.building_id,
        )
        return MLTrainingResult(
            tenant_id=input.tenant_id,
            building_id=input.building_id,
            model_type="autoencoder",
            mlflow_run_id="",
            model_artifact_uri="",
            scaler_artifact_uri="",
            n_training_samples=0,
            status="skipped",
            detail="No usable training features available.",
        )

    activity.heartbeat()

    from models.training.autoencoder import AutoencoderTrainer
    from services.ml_ensemble.config import MLEnsembleConfig

    trainer = AutoencoderTrainer()
    result = trainer.train(
        tenant_id=tenant_id,
        building_id=building_id,
        features=features,
        config=MLEnsembleConfig(),
        mlflow_tracking_uri=input.mlflow_tracking_uri,
        training_trigger=input.trigger,
    )

    logger.info(
        "train_autoencoder_activity: complete tenant=%s building=%s run_id=%s samples=%d",
        input.tenant_id,
        input.building_id,
        result.mlflow_run_id,
        result.n_training_samples,
    )

    return MLTrainingResult(
        tenant_id=input.tenant_id,
        building_id=input.building_id,
        model_type="autoencoder",
        mlflow_run_id=result.mlflow_run_id,
        model_artifact_uri=result.model_artifact.artifact_uri,
        scaler_artifact_uri=result.scaler_artifact.artifact_uri,
        n_training_samples=result.n_training_samples,
        status="completed",
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


async def _fetch_training_features(
    tenant_id: UUID,
    building_id: UUID,
) -> list:
    """Fetch pre-assembled FeatureSetV1 rows for training.

    TODO(ENG-6b): Replace this stub with a real feature store query that:
      1. Connects via an RLS-enforced read replica using tenant_id credentials.
      2. Queries the feature store table for rows within the training window
         (e.g., 90 days of hourly data).
      3. Returns List[FeatureSetV1] for the given (tenant, building) pair.
    ENG-6b owns the training pipeline with three retraining triggers (calendar,
    drift, feedback-volume) and is responsible for wiring this to the feature store
    (depends on ENG-2d database infrastructure). ENG-4 is the Optimization Engine
    and is unrelated to ML training feature fetches.

    For now returns an empty list; the activity handles the skip path.
    """
    logger.debug(
        "_fetch_training_features: stub — no feature store connected for tenant=%s building=%s",
        tenant_id,
        building_id,
    )
    return []
