"""ENG-6c — train -> evaluate -> gate -> (promote | hold) for one
(tenant, building), reusing the exact same trainers, feature store, and
promotion gate the Temporal retraining activity (ENG-6d) also uses --
this module exists so the same flow is runnable directly (a script, a
test, an ad hoc backfill-then-train pass) without needing a live Temporal
worker.
"""

from __future__ import annotations

import dataclasses
import datetime
import logging
from uuid import UUID

from models.evaluation.promotion_gate import PromotionDecision, PromotionGate
from models.feature_store.repository import FeatureStoreRepository
from models.registry.mlflow_registry import MLflowModelRegistry
from models.training.autoencoder import AutoencoderTrainer
from models.training.isolation_forest import IsolationForestTrainer
from services.ml_ensemble.config import MLEnsembleConfig
from services.ml_ensemble.models import TrainingRunResult
from shared.auth.tenant_context import tenant_scope
from shared.database import get_session_factory

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class ModelTrainingOutcome:
    result: TrainingRunResult
    decision: PromotionDecision


@dataclasses.dataclass
class TrainAndEvaluateSummary:
    tenant_id: UUID
    building_id: UUID
    trigger: str
    n_features_used: int
    outcomes: list[ModelTrainingOutcome] = dataclasses.field(default_factory=list)
    skipped_reason: str | None = None


async def train_and_evaluate(
    tenant_id: UUID,
    building_id: UUID,
    building_type: str = "unknown",
    trigger: str = "calendar",
    window_days: int = 90,
    mlflow_tracking_uri: str = "",
    promotion_gate: PromotionGate | None = None,
    registry: MLflowModelRegistry | None = None,
) -> TrainAndEvaluateSummary:
    """Trains both ensemble members, evaluates each against the promotion
    gate, and promotes any approved candidate. A model that fails the gate
    (or is held for human review) stays registered-but-unpromoted -- the
    previously-promoted version, if any, keeps serving unchanged (TRD
    v2.0 §6.3).
    """
    window_end = datetime.datetime.now(datetime.UTC)
    window_start = window_end - datetime.timedelta(days=window_days)

    factory = get_session_factory()
    async with factory() as session, tenant_scope(session, tenant_id):
        features = await FeatureStoreRepository(session).get_features_for_building(
            tenant_id, building_id, window_start, window_end
        )

    summary = TrainAndEvaluateSummary(
        tenant_id=tenant_id, building_id=building_id, trigger=trigger, n_features_used=len(features)
    )

    usable = [f for f in features if not f.low_data_quality]
    if len(usable) < 2:
        summary.skipped_reason = (
            f"Only {len(usable)} usable (low_data_quality=False) feature rows in the "
            f"{window_days}-day window -- need at least 2 to train."
        )
        logger.warning(
            "train_and_evaluate: skipping tenant=%s building=%s -- %s",
            tenant_id,
            building_id,
            summary.skipped_reason,
        )
        return summary

    gate = promotion_gate or PromotionGate()
    reg = registry or MLflowModelRegistry(tracking_uri=mlflow_tracking_uri or None)
    config = MLEnsembleConfig()

    if_trainer = IsolationForestTrainer()
    if_result = if_trainer.train(
        tenant_id=tenant_id,
        building_id=building_id,
        features=features,
        config=config,
        building_type=building_type,
        mlflow_tracking_uri=mlflow_tracking_uri,
        training_trigger=trigger,
    )
    summary.outcomes.append(
        await _evaluate_and_promote(if_result, gate, reg, tenant_id, building_id)
    )

    ae_trainer = AutoencoderTrainer()
    ae_result = ae_trainer.train(
        tenant_id=tenant_id,
        building_id=building_id,
        features=features,
        config=config,
        mlflow_tracking_uri=mlflow_tracking_uri,
        training_trigger=trigger,
    )
    summary.outcomes.append(
        await _evaluate_and_promote(ae_result, gate, reg, tenant_id, building_id)
    )

    return summary


async def _evaluate_and_promote(
    result: TrainingRunResult,
    gate: PromotionGate,
    registry: MLflowModelRegistry,
    tenant_id: UUID,
    building_id: UUID,
) -> ModelTrainingOutcome:
    factory = get_session_factory()
    async with factory() as session, tenant_scope(session, tenant_id):
        decision = await gate.evaluate(session, result)
        await session.commit()

    if decision.approved and result.registered_version is not None:
        registry.promote(tenant_id, building_id, result.model_type, result.registered_version)
        logger.info(
            "train_and_evaluate: promoted %s version=%s for tenant=%s building=%s",
            result.model_type,
            result.registered_version,
            tenant_id,
            building_id,
        )
    else:
        logger.info(
            "train_and_evaluate: NOT promoted (%s) %s for tenant=%s building=%s -- %s",
            "human review pending" if decision.requires_human_review else "rejected",
            result.model_type,
            tenant_id,
            building_id,
            decision.reason,
        )

    return ModelTrainingOutcome(result=result, decision=decision)
