"""ENG-6c (ROADMAP ENG-6c) — promotion gate for a freshly-trained candidate.

TRD v2.0 §6.3's shadow-mode gate compares a candidate against "the
building's held-out labeled feedback set" -- but a just-trained candidate
has never served a single prediction, so no feedback exists *about it*
yet (feedback accrues only after a model has been promoted and is
generating findings a human can confirm/dismiss). This gate therefore
runs two independent checks appropriate to what's actually knowable at
training-completion time:

1. A sanity check against the candidate's own training-time metrics
   (sample size, anomaly rate within a plausible band) -- catching an
   obviously miscalibrated candidate before it ever reaches production,
   the one thing genuinely knowable before promotion.
2. A tiered human-review requirement for a building's first N promotions
   (TRD v2.0 §6.3), tracked via the audit trail (models/registry/audit.py)
   rather than re-derived from MLflow version history, which doesn't
   distinguish "registered" from "ever promoted."

Post-promotion false-positive-rate regression against real feedback is a
*different* mechanism -- models/evaluation/rollback.py, run periodically
against the live serving model, not at promotion time (TRD v2.0 §6.4).

EMPIRICAL VALIDATION REQUIRED: max_reasonable_anomaly_rate and
human_review_required_first_n_promotions are placeholder defaults, not
calibrated thresholds -- DATA_AND_MODEL_STRATEGY explicitly flags the
false-positive-rate ceiling as "not yet numerically set... a joint
Product/Engineering decision" (PRD §8.4). Tier-differentiated review
counts (freemium vs. enterprise/compliance, per TRD v2.0 §6.3) are not
implemented -- every tenant uses the same threshold pending that product
decision; noted explicitly, not silently assumed away.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic_settings import BaseSettings
from sqlalchemy.ext.asyncio import AsyncSession

from models.registry.audit import count_promotions, log_model_event
from services.ml_ensemble.models import TrainingRunResult


class PromotionGateSettings(BaseSettings):
    model_config = {"env_prefix": "PROMOTION_GATE_"}

    min_training_samples: int = 50
    max_reasonable_anomaly_rate: float = 0.25
    human_review_required_first_n_promotions: int = 3


@dataclass(frozen=True)
class PromotionDecision:
    approved: bool
    reason: str
    requires_human_review: bool = False


class PromotionGate:
    def __init__(self, settings: PromotionGateSettings | None = None) -> None:
        self._settings = settings or PromotionGateSettings()

    async def evaluate(
        self,
        session: AsyncSession,
        result: TrainingRunResult,
    ) -> PromotionDecision:
        """Evaluate a just-trained candidate. Caller must have already
        entered tenant_scope(session, result.tenant_id) and must call
        session.commit() afterward -- this method only queries/writes
        audit_log, it does not manage the transaction."""
        if result.registered_version is None:
            decision = PromotionDecision(
                approved=False, reason="Model Registry registration did not succeed."
            )
            await self._log(session, result, decision)
            return decision

        if result.n_training_samples < self._settings.min_training_samples:
            decision = PromotionDecision(
                approved=False,
                reason=(
                    f"Insufficient training samples ({result.n_training_samples} < "
                    f"{self._settings.min_training_samples})."
                ),
            )
            await self._log(session, result, decision)
            return decision

        anomaly_rate = result.metrics.get("train_anomaly_rate")
        if anomaly_rate is not None and anomaly_rate > self._settings.max_reasonable_anomaly_rate:
            decision = PromotionDecision(
                approved=False,
                reason=(
                    f"train_anomaly_rate {anomaly_rate:.3f} exceeds the sanity bound "
                    f"{self._settings.max_reasonable_anomaly_rate:.3f} -- likely miscalibrated."
                ),
            )
            await self._log(session, result, decision)
            return decision

        prior_promotions = await count_promotions(
            session, result.tenant_id, result.building_id, result.model_type
        )
        requires_review = prior_promotions < self._settings.human_review_required_first_n_promotions
        decision = PromotionDecision(
            approved=not requires_review,
            reason=(
                "Passed automated checks; held for human review "
                f"(promotion #{prior_promotions + 1} of first "
                f"{self._settings.human_review_required_first_n_promotions})."
                if requires_review
                else "Passed automated checks; auto-promoted."
            ),
            requires_human_review=requires_review,
        )
        await self._log(session, result, decision)
        return decision

    async def _log(
        self, session: AsyncSession, result: TrainingRunResult, decision: PromotionDecision
    ) -> None:
        event_type = "model.promoted" if decision.approved else "model.promotion_rejected"
        await log_model_event(
            session,
            tenant_id=result.tenant_id,
            event_type=event_type,
            payload={
                "building_id": str(result.building_id),
                "model_type": result.model_type,
                "mlflow_run_id": result.mlflow_run_id,
                "registered_version": result.registered_version,
                "training_trigger": result.training_trigger,
                "n_training_samples": result.n_training_samples,
                "metrics": result.metrics,
                "approved": decision.approved,
                "requires_human_review": decision.requires_human_review,
                "reason": decision.reason,
                "promoting_actor": "automated_gate",
            },
        )


__all__ = ["PromotionDecision", "PromotionGate", "PromotionGateSettings"]
