"""ENG-6c (ROADMAP ENG-6c) — model evaluation metrics against real feedback.

TRD v2.0 §6.3's promotion gate is a false-positive-rate regression check
against "the building's held-out labeled feedback set" -- feedback_labels
is that set: a `dismissed` action against an ml_ensemble-origin finding is
the platform's only real signal that the model flagged something a human
reviewer judged not-anomalous (a false positive); `confirmed` is the
converse signal. There is no separate held-out label store to build --
feedback_labels already accumulates exactly this, per DATA_AND_MODEL_STRATEGY
§8's framing of feedback as evaluation + retraining-trigger-volume input
(never a direct training target).

Findings don't distinguish which ML Ensemble member (isolation_forest vs.
autoencoder) produced a given ml_ensemble-origin finding -- layer_origin
is the ensemble as a whole (services/rules_engine/models.py's
VALID_LAYERS). Evaluation therefore operates at that same granularity:
one false-positive rate per (tenant, building) covering the ensemble's
combined output, which is the only signal the schema actually carries.
"""

from __future__ import annotations

import datetime
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class ModelEvaluationMetrics(BaseModel):
    tenant_id: UUID
    building_id: UUID
    window_start: datetime.datetime
    window_end: datetime.datetime
    n_confirmed: int = Field(ge=0)
    n_dismissed: int = Field(ge=0)

    @property
    def n_labeled(self) -> int:
        return self.n_confirmed + self.n_dismissed

    @property
    def false_positive_rate(self) -> float | None:
        """None when there is no labeled feedback yet in the window --
        callers must treat that as "cannot evaluate," never as a rate of
        0.0 (an absence of labels is not evidence of a perfect model)."""
        if self.n_labeled == 0:
            return None
        return self.n_dismissed / self.n_labeled


async def compute_false_positive_rate(
    session: AsyncSession,
    tenant_id: UUID,
    building_id: UUID,
    window_start: datetime.datetime,
    window_end: datetime.datetime,
) -> ModelEvaluationMetrics:
    """Caller must have already entered tenant_scope(session, tenant_id),
    matching every other repository-style query in this codebase."""
    stmt = text(
        """
        SELECT fl.action, COUNT(*) AS n
        FROM feedback_labels fl
        JOIN findings f ON fl.finding_id = f.finding_id
        WHERE f.tenant_id = :tenant_id
          AND f.building_id = :building_id
          AND f.layer_origin = 'ml_ensemble'
          AND fl.created_at >= :window_start
          AND fl.created_at <= :window_end
        GROUP BY fl.action
        """
    )
    result = await session.execute(
        stmt,
        {
            "tenant_id": str(tenant_id),
            "building_id": str(building_id),
            "window_start": window_start,
            "window_end": window_end,
        },
    )
    counts = {row.action: row.n for row in result.fetchall()}

    return ModelEvaluationMetrics(
        tenant_id=tenant_id,
        building_id=building_id,
        window_start=window_start,
        window_end=window_end,
        n_confirmed=counts.get("confirmed", 0),
        n_dismissed=counts.get("dismissed", 0),
    )
