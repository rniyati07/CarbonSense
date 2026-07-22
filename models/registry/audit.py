"""ENG-6a/6c/6d — model-lifecycle audit trail.

TRD v2.0 §6.1: "Every promoted version records: training data window,
training trigger... evaluation metrics at promotion time, and the
promoting actor... satisfying the audit-log retention requirement (PRD
§6) at the model layer, not just the findings layer." audit_log already
exists (migration 0001), is RLS-protected, and is INSERT+SELECT only (no
UPDATE/DELETE grant) -- exactly the append-only guarantee a promotion/
rollback trail needs. Model-lifecycle events reuse it rather than a new
table, matching the "reuse existing services" constraint.

Event types written here: model.registered, model.promoted,
model.promotion_rejected, model.rollback.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def log_model_event(
    session: AsyncSession,
    tenant_id: UUID,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    stmt = text(
        """
        INSERT INTO audit_log (tenant_id, event_type, payload)
        VALUES (:tenant_id, :event_type, :payload)
        """
    )
    await session.execute(
        stmt,
        {
            "tenant_id": str(tenant_id),
            "event_type": event_type,
            "payload": json.dumps(payload, default=str),
        },
    )


async def count_promotions(
    session: AsyncSession,
    tenant_id: UUID,
    building_id: UUID,
    model_type: str,
) -> int:
    """How many times a (building, model_type) has been promoted before --
    the human-review gate's input signal (TRD v2.0 §6.3: "applies to a
    tenant's first N promotions")."""
    stmt = text(
        """
        SELECT COUNT(*) AS n
        FROM audit_log
        WHERE tenant_id = :tenant_id
          AND event_type = 'model.promoted'
          AND payload->>'building_id' = :building_id
          AND payload->>'model_type' = :model_type
        """
    )
    result = await session.execute(
        stmt,
        {
            "tenant_id": str(tenant_id),
            "building_id": str(building_id),
            "model_type": model_type,
        },
    )
    row = result.fetchone()
    return int(row.n) if row is not None else 0
