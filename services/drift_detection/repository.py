from __future__ import annotations

import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.ingestion.models import NormalizedReading


class DatabaseDriftRepository:
    """Repository for fetching historical normalized readings for drift detection."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_building_context(self, building_id: UUID) -> tuple[str, str | None]:
        """Fetch building type and climate zone."""
        query = text("SELECT building_type, climate_zone FROM buildings WHERE building_id = :b_id")
        result = await self._session.execute(query, {"b_id": str(building_id)})
        row = result.fetchone()
        if row:
            return row[0], row[1]
        return "office", None

    async def get_trailing_readings(
        self, tenant_id: UUID, building_id: UUID, days: int = 30
    ) -> list[NormalizedReading]:
        """Fetch normalized readings for the trailing window."""
        now = datetime.datetime.now(datetime.UTC)
        start_time = now - datetime.timedelta(days=days)

        # CONFIRMED BUG (pre-ENG-4 integration audit): this query string used
        # `\"\"\"` (escaped quotes inside a plain, non-raw string) instead of
        # `"""`, a SyntaxError that broke this module's entire import chain
        # (repository.py -> drift_detection_stub.py -> the drift_detection.py
        # workflow -> its own test file). Fixed below; no other change.
        query = text(
            """
            SELECT nr.ts, nr.kwh, nr.rolling_baseline_kwh, nr.data_quality_status, nr.circuit_id,
                   nr.schema_version
            FROM normalized_readings nr
            JOIN submeter_circuits sc ON nr.circuit_id = sc.circuit_id
            WHERE sc.building_id = :b_id AND nr.ts >= :start_time
            """
        )

        result = await self._session.execute(
            query, {"b_id": str(building_id), "start_time": start_time}
        )
        readings = []

        for row in result:
            readings.append(
                NormalizedReading(
                    tenant_id=tenant_id,
                    circuit_id=row.circuit_id,
                    ts=row.ts,
                    kwh=row.kwh,
                    rolling_baseline_kwh=row.rolling_baseline_kwh,
                    data_quality_status=row.data_quality_status,
                    schema_version=row.schema_version,
                    source_system="db",
                    ingestion_timestamp=now,
                    normalization_version="v1",
                )
            )
        return readings
