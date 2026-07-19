"""ENG-5d — analysis_jobs data access, backing the Scenario API's
POST /v1/scenarios/analyze 202+poll endpoint (TRD v2.0 §7.3's own literal
example). See database/migrations/versions/0008_api_platform.py's docstring
for why this is a separate, lighter-weight mechanism than
AnalysisPipelineWorkflow's Temporal orchestration.
"""

from __future__ import annotations

import json
from typing import Any, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class AnalysisJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, tenant_id: UUID, building_ids: list[UUID]) -> UUID:
        stmt = text(
            """
            INSERT INTO analysis_jobs (tenant_id, building_ids)
            VALUES (:tenant_id, :building_ids)
            RETURNING job_id
            """
        )
        result = await self._session.execute(
            stmt,
            {
                "tenant_id": str(tenant_id),
                "building_ids": json.dumps([str(b) for b in building_ids]),
            },
        )
        row = result.fetchone()
        assert row is not None
        return cast(UUID, row.job_id)

    async def mark_completed(self, tenant_id: UUID, job_id: UUID, result: dict[str, Any]) -> None:
        stmt = text(
            """
            UPDATE analysis_jobs
            SET status = 'completed', result = :result, completed_at = now()
            WHERE tenant_id = :tenant_id AND job_id = :job_id
            """
        )
        await self._session.execute(
            stmt,
            {"tenant_id": str(tenant_id), "job_id": str(job_id), "result": json.dumps(result)},
        )

    async def mark_failed(self, tenant_id: UUID, job_id: UUID, error: str) -> None:
        stmt = text(
            """
            UPDATE analysis_jobs
            SET status = 'failed', error = :error, completed_at = now()
            WHERE tenant_id = :tenant_id AND job_id = :job_id
            """
        )
        await self._session.execute(
            stmt, {"tenant_id": str(tenant_id), "job_id": str(job_id), "error": error}
        )

    async def get(self, tenant_id: UUID, job_id: UUID) -> dict[str, Any] | None:
        stmt = text(
            """
            SELECT job_id, status, building_ids, result, error, created_at, completed_at
            FROM analysis_jobs
            WHERE tenant_id = :tenant_id AND job_id = :job_id
            """
        )
        result = await self._session.execute(
            stmt, {"tenant_id": str(tenant_id), "job_id": str(job_id)}
        )
        row = result.fetchone()
        if row is None:
            return None
        job_result = row.result
        if isinstance(job_result, str):
            job_result = json.loads(job_result)
        return {
            "job_id": row.job_id,
            "status": row.status,
            "result": job_result,
            "error": row.error,
            "created_at": row.created_at,
            "completed_at": row.completed_at,
        }
