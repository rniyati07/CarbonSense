"""ENG-3c — STL Residual Detection calendar repository implementations.

Provides:
    InMemoryCalendarRepository
        Test/stub implementation of the CalendarRepository Protocol.
        Suitable for unit tests and local development.  Backed by a
        plain Python dict — no external dependencies.

    TimescaleCalendarRepository (ENG-1d, implemented as part of the
    ENG-2c pipeline-wiring pass)
        Queries the building_calendar table via an RLS-enforced
        SQLAlchemy async session, following the same pattern as
        services/calibration/repository.py and
        services/drift_detection/repository.py.

        ARCHITECTURE NOTE: CalendarRepository.get_calendar_entries() is
        declared as a *synchronous* method on the Protocol (see
        interfaces.py), because STLDetectionService.analyse_circuit_window()
        is itself synchronous (STL decomposition is CPU-bound, not I/O).
        A DB-backed implementation cannot satisfy that sync signature
        without either blocking the event loop inside an async Temporal
        activity (unsafe) or making the Protocol async (would change
        STLDetectionService's own interface -- out of scope, since the
        task requires preserving existing services unchanged). Changing
        the Protocol was considered and rejected for this reason.

        Resolution: TimescaleCalendarRepository exposes an async
        `fetch_calendar_entries()` method. The Temporal activity awaits
        it once per analysis window, then constructs an
        InMemoryCalendarRepository from the result and injects *that*
        into STLDetectionService -- reusing the existing, already-correct
        sync repository exactly as designed, with real data now behind
        it. STLDetectionService's code is untouched.
"""

from __future__ import annotations

import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.ingestion.models import NormalizedReading
from services.stl_detection.models import CalendarEntry, DayType


class InMemoryCalendarRepository:
    """In-memory implementation of CalendarRepository for tests and stubs.

    Backed by a dict keyed on (building_id, date) for O(1) lookups.

    Parameters
    ----------
    entries:
        Pre-loaded CalendarEntry objects.  Call add() to extend after
        construction, or pass the full list at construction time.

    Usage
    -----
    ::

        repo = InMemoryCalendarRepository([
            CalendarEntry(building_id=..., date=date(2026,1,1), day_type=DayType.HOLIDAY),
            CalendarEntry(building_id=..., date=date(2026,1,2), day_type=DayType.WEEKEND),
        ])
        entries = repo.get_calendar_entries(building_id, start, end)
    """

    def __init__(self, entries: list[CalendarEntry] | None = None) -> None:
        self._store: dict[tuple[UUID, datetime.date], CalendarEntry] = {}
        for entry in entries or []:
            self.add(entry)

    def add(self, entry: CalendarEntry) -> None:
        """Insert or overwrite a CalendarEntry."""
        self._store[(entry.building_id, entry.date)] = entry

    def add_many(self, entries: list[CalendarEntry]) -> None:
        """Bulk-insert CalendarEntry objects."""
        for entry in entries:
            self.add(entry)

    def get_calendar_entries(
        self,
        building_id: UUID,
        start_date: datetime.date,
        end_date: datetime.date,
    ) -> list[CalendarEntry]:
        """Return all stored entries for building_id within [start_date, end_date].

        Returns an empty list for dates that have no entry — the service
        will raise CalendarLookupError for any missing date, as required
        by the calendar-awareness hard constraint.
        """
        results: list[CalendarEntry] = []
        current = start_date
        while current <= end_date:
            entry = self._store.get((building_id, current))
            if entry is not None:
                results.append(entry)
            current += datetime.timedelta(days=1)
        return results


class TimescaleCalendarRepository:
    """Real, DB-backed calendar fetch (ENG-1d). See module docstring for why
    this exposes an async fetch method rather than implementing the sync
    CalendarRepository Protocol directly."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def fetch_calendar_entries(
        self,
        building_id: UUID,
        start_date: datetime.date,
        end_date: datetime.date,
    ) -> list[CalendarEntry]:
        stmt = text(
            """
            SELECT building_id, date, day_type
            FROM building_calendar
            WHERE building_id = :building_id
              AND date >= :start_date
              AND date <= :end_date
            """
        )
        result = await self._session.execute(
            stmt,
            {
                "building_id": str(building_id),
                "start_date": start_date,
                "end_date": end_date,
            },
        )
        return [
            CalendarEntry(
                building_id=row.building_id,
                date=row.date,
                day_type=DayType(row.day_type),
            )
            for row in result.fetchall()
        ]


class STLReadingsRepository:
    """Fetches normalized_readings grouped by circuit for STL analysis.

    STLDetectionService.analyse_circuit_window() operates on one circuit's
    readings at a time (see its docstring) and type-hints
    services.ingestion.models.NormalizedReading directly (not the flexible
    dict-or-object shape rules_engine accepts) -- real objects are
    constructed here, following the identical raw-SQL-to-NormalizedReading
    pattern already used by services/drift_detection/repository.py.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_readings_by_circuit(
        self,
        building_id: UUID,
        window_start: datetime.datetime,
        window_end: datetime.datetime,
    ) -> dict[UUID, list[NormalizedReading]]:
        stmt = text(
            """
            SELECT nr.tenant_id, nr.circuit_id, nr.ts, nr.kwh, nr.is_peak_hour,
                   nr.rolling_baseline_kwh, nr.data_quality_status, nr.schema_version
            FROM normalized_readings nr
            JOIN submeter_circuits sc ON nr.circuit_id = sc.circuit_id
            WHERE sc.building_id = :building_id
              AND nr.ts >= :window_start
              AND nr.ts <= :window_end
              AND nr.data_quality_status IN ('pass', 'degraded')
            ORDER BY nr.circuit_id, nr.ts
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
        now = datetime.datetime.now(datetime.UTC)
        by_circuit: dict[UUID, list[NormalizedReading]] = {}
        for row in result.fetchall():
            by_circuit.setdefault(row.circuit_id, []).append(
                NormalizedReading(
                    tenant_id=row.tenant_id,
                    circuit_id=row.circuit_id,
                    ts=row.ts,
                    kwh=row.kwh,
                    is_peak_hour=row.is_peak_hour,
                    rolling_baseline_kwh=row.rolling_baseline_kwh,
                    data_quality_status=row.data_quality_status,
                    schema_version=row.schema_version,
                    source_system="db",
                    ingestion_timestamp=now,
                    normalization_version="v1",
                )
            )
        return by_circuit
