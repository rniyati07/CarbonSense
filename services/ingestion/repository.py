"""ENG-2c-wiring — lightweight Data Quality Gate verification (revised per
approval: the Gate stays in AnalysisPipelineWorkflow rather than being
removed, but as a check against already-persisted data, not a re-run of
DataQualityGate.process_batch() -- that method requires the raw,
pre-normalization batch (RawIngestionBatch.raw_rows, circuit_map), which
does not exist once ingestion has completed and cannot be reconstructed
from normalized_readings.

TRD v2.0 3.1's own rule -- "a quarantined-only batch does not trigger
downstream analysis and instead raises a data-quality alert to the
tenant" -- is what this repository lets the retained
data_quality_gate_activity re-check against the persisted record, using
the same async-SQLAlchemy-session, tenant-scoped-caller pattern as
services/calibration/repository.py and services/drift_detection/repository.py.
"""

from __future__ import annotations

import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class DataQualityVerificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_status_counts(
        self,
        building_id: UUID,
        window_start: datetime.datetime,
        window_end: datetime.datetime,
    ) -> dict[str, int]:
        """Return {data_quality_status: count} for readings in the window.

        Missing statuses are simply absent from the returned dict --
        callers should use .get(status, 0).
        """
        stmt = text(
            """
            SELECT nr.data_quality_status, COUNT(*) AS n
            FROM normalized_readings nr
            JOIN submeter_circuits sc ON nr.circuit_id = sc.circuit_id
            WHERE sc.building_id = :building_id
              AND nr.ts >= :window_start
              AND nr.ts <= :window_end
            GROUP BY nr.data_quality_status
            """
        )
        result = await self._session.execute(
            stmt,
            {
                "building_id": str(building_id),
                "window_start": window_start,
                "window_end": window_end,
            },
        )
        return {row.data_quality_status: row.n for row in result.fetchall()}
