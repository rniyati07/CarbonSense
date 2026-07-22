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

from models.feature_store.feature_set_v1 import FeatureSetV1
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
    window_days: int = 90,
) -> list[FeatureSetV1]:
    """Fetch pre-assembled FeatureSetV1 rows for training from the feature
    store (ENG-6, migration 0009) -- populated by feature_assembly_activity
    on every real AnalysisPipelineWorkflow run (analysis_stubs.py) and by
    the batch feature-engineering pipeline (pipelines/feature_engineering/)
    when backfilling from a bulk-ingested public dataset (ENG-6a/6b).

    window_days=90 matches the training-window default already documented
    on the RLS-enforced query path (analysis_stubs.py's window_days=30 is
    the *analysis* window; training wants more history where available).
    """
    import datetime

    from models.feature_store.repository import FeatureStoreRepository
    from shared.auth.tenant_context import tenant_scope
    from shared.database import get_session_factory

    window_end = datetime.datetime.now(datetime.UTC)
    window_start = window_end - datetime.timedelta(days=window_days)

    factory = get_session_factory()
    async with factory() as session, tenant_scope(session, tenant_id):
        features = await FeatureStoreRepository(session).get_features_for_building(
            tenant_id, building_id, window_start, window_end
        )

    logger.debug(
        "_fetch_training_features: found %d feature_store rows for tenant=%s building=%s "
        "(window=%dd)",
        len(features),
        tenant_id,
        building_id,
        window_days,
    )
    return features
