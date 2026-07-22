"""ENG-6d (ROADMAP ENG-6d, TRD v2.0 §6.4) — automatic post-promotion rollback.

Distinct from PromotionGate (models/evaluation/promotion_gate.py), which
runs once, at training completion, before a candidate has ever served a
prediction. RollbackMonitor runs periodically against a model that IS
currently serving (the champion alias), using the real feedback that has
since accumulated -- exactly the signal a just-trained candidate could
never have had. "The registry retains the last K promoted versions... in
a hot-swappable state" (TRD v2.0 §6.4) is what MLflowModelRegistry's
version history already gives for free; rollback here is just re-pointing
the champion alias to the immediately-prior version.

EMPIRICAL VALIDATION REQUIRED: max_fp_rate and min_sample_size are
placeholder defaults -- see promotion_gate.py's identical caveat and
DATA_AND_MODEL_STRATEGY's explicit "ceiling not yet numerically set" note.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from uuid import UUID

from pydantic_settings import BaseSettings
from sqlalchemy.ext.asyncio import AsyncSession

from models.evaluation.metrics import compute_false_positive_rate
from models.registry.audit import log_model_event
from models.registry.mlflow_registry import MLflowModelRegistry


class RollbackSettings(BaseSettings):
    model_config = {"env_prefix": "ROLLBACK_"}

    max_fp_rate: float = 0.3
    min_sample_size: int = 10


@dataclass(frozen=True)
class RollbackDecision:
    rolled_back: bool
    reason: str
    new_champion_version: str | None = None


class RollbackMonitor:
    def __init__(
        self,
        registry: MLflowModelRegistry,
        settings: RollbackSettings | None = None,
    ) -> None:
        self._registry = registry
        self._settings = settings or RollbackSettings()

    async def check_and_rollback(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        building_id: UUID,
        model_type: str,
        window_start: datetime.datetime,
        window_end: datetime.datetime,
    ) -> RollbackDecision:
        """Caller must have already entered
        tenant_scope(session, tenant_id) and must call session.commit()
        afterward -- this method only queries/writes audit_log, it does
        not manage the transaction."""
        metrics = await compute_false_positive_rate(
            session, tenant_id, building_id, window_start, window_end
        )

        if metrics.n_labeled < self._settings.min_sample_size:
            return RollbackDecision(
                rolled_back=False,
                reason=(
                    f"Only {metrics.n_labeled} labeled feedback rows in window "
                    f"(< {self._settings.min_sample_size}) -- too few to evaluate."
                ),
            )

        fp_rate = metrics.false_positive_rate
        assert fp_rate is not None  # n_labeled >= min_sample_size > 0, checked above

        if fp_rate <= self._settings.max_fp_rate:
            return RollbackDecision(
                rolled_back=False,
                reason=f"false_positive_rate={fp_rate:.3f} within ceiling "
                f"{self._settings.max_fp_rate:.3f}.",
            )

        previous_version = self._registry.get_previous_version(tenant_id, building_id, model_type)
        if previous_version is None:
            reason = (
                f"false_positive_rate={fp_rate:.3f} exceeds ceiling "
                f"{self._settings.max_fp_rate:.3f} but no prior version exists to roll back to."
            )
            await log_model_event(
                session,
                tenant_id=tenant_id,
                event_type="model.rollback",
                payload={
                    "building_id": str(building_id),
                    "model_type": model_type,
                    "false_positive_rate": fp_rate,
                    "n_labeled": metrics.n_labeled,
                    "rolled_back": False,
                    "reason": reason,
                },
            )
            return RollbackDecision(rolled_back=False, reason=reason)

        current_version = self._registry.get_champion_version(tenant_id, building_id, model_type)
        self._registry.promote(tenant_id, building_id, model_type, previous_version)

        reason = (
            f"false_positive_rate={fp_rate:.3f} exceeded ceiling "
            f"{self._settings.max_fp_rate:.3f} ({metrics.n_labeled} labeled samples) -- "
            f"rolled back from version {current_version} to {previous_version}."
        )
        await log_model_event(
            session,
            tenant_id=tenant_id,
            event_type="model.rollback",
            payload={
                "building_id": str(building_id),
                "model_type": model_type,
                "false_positive_rate": fp_rate,
                "n_labeled": metrics.n_labeled,
                "rolled_back": True,
                "from_version": current_version,
                "to_version": previous_version,
                "reason": reason,
            },
        )
        return RollbackDecision(
            rolled_back=True, reason=reason, new_champion_version=previous_version
        )


__all__ = ["RollbackDecision", "RollbackMonitor", "RollbackSettings"]
