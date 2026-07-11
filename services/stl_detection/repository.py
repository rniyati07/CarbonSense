"""ENG-3c — STL Residual Detection calendar repository implementations.

Provides:
    InMemoryCalendarRepository
        Test/stub implementation of the CalendarRepository Protocol.
        Suitable for unit tests and local development.  Backed by a
        plain Python dict — no external dependencies.

    TODO (ENG-1d wiring):
        Add TimescaleCalendarRepository once the building_calendar
        TimescaleDB table and RLS policies are provisioned by ENG-1d.
        That implementation will query through an RLS-enforced SQLAlchemy
        async session and return CalendarEntry objects matching the Protocol.
        Scaffold is not included here to avoid introducing an unmigrated DB
        dependency before ENG-1d is complete.
"""

from __future__ import annotations

import datetime
from uuid import UUID

from services.stl_detection.models import CalendarEntry


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
