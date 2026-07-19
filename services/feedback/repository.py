"""ENG-5 prerequisite — FeedbackRepository.

Follows the same async-SQLAlchemy-session, tenant-scoped-caller (RLS)
pattern as services/calibration/repository.py and
services/optimization/repository.py -- the sync, dual-connection-type
FeedbackService this replaces (raw DB-API cursor or sync SQLAlchemy
Connection, manually issuing `SET LOCAL app.current_tenant_id`) predates
that convention and was the last holdout.
"""

from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class FindingForFeedback:
    def __init__(self, building_id: UUID, explainability_bundle: dict[str, object] | None) -> None:
        self.building_id = building_id
        self.explainability_bundle = explainability_bundle


class FeedbackRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_finding_for_feedback(self, finding_id: UUID) -> FindingForFeedback | None:
        stmt = text(
            "SELECT building_id, explainability_bundle FROM findings WHERE finding_id = :fid"
        )
        result = await self._session.execute(stmt, {"fid": str(finding_id)})
        row = result.fetchone()
        if row is None:
            return None

        bundle = row.explainability_bundle
        if isinstance(bundle, str):
            bundle = json.loads(bundle)
        return FindingForFeedback(building_id=row.building_id, explainability_bundle=bundle)

    async def save_feedback_label(
        self,
        feedback_id: UUID,
        tenant_id: UUID,
        finding_id: UUID,
        action: str,
        actor: str,
        created_at: object,
    ) -> None:
        stmt = text(
            "INSERT INTO feedback_labels "
            "(feedback_id, tenant_id, finding_id, action, actor, created_at) "
            "VALUES (:feedback_id, :tenant_id, :finding_id, :action, :actor, :created_at)"
        )
        await self._session.execute(
            stmt,
            {
                "feedback_id": str(feedback_id),
                "tenant_id": str(tenant_id),
                "finding_id": str(finding_id),
                "action": action,
                "actor": actor,
                "created_at": created_at,
            },
        )

    async def update_finding_status(self, finding_id: UUID, status: str) -> None:
        stmt = text("UPDATE findings SET status = :status WHERE finding_id = :fid")
        await self._session.execute(stmt, {"status": status, "fid": str(finding_id)})

    async def count_feedback_for_building(self, tenant_id: UUID, building_id: UUID) -> int:
        stmt = text(
            "SELECT COUNT(*) FROM feedback_labels fl "
            "JOIN findings f ON fl.finding_id = f.finding_id "
            "WHERE f.building_id = :bid AND fl.tenant_id = :tid"
        )
        result = await self._session.execute(stmt, {"bid": str(building_id), "tid": str(tenant_id)})
        return int(result.scalar() or 0)
