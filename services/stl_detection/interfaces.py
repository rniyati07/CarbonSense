"""ENG-3c — STL Residual Detection interfaces (Protocols).

Protocol definitions for injectable collaborators used by
STLDetectionService.  Using Protocol (structural typing) keeps the service
decoupled from any specific storage implementation — a test can inject an
InMemoryCalendarRepository and production can inject a DB-backed one without
the service needing to know which it has.

CalendarRepository
    Abstraction over the building_calendar table (ENG-1d).
    STLDetectionService depends only on this interface.
"""

from __future__ import annotations

import datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from services.stl_detection.models import CalendarEntry


@runtime_checkable
class CalendarRepository(Protocol):
    """Read-only access to the building_calendar table.

    The STL service queries this to obtain day_type classifications for
    the readings it is decomposing.  It never writes to the calendar.

    Notes
    -----
    - The returned list must include an entry for every date that appears
      in the analysis window.  Any missing date causes CalendarLookupError.
    - Implementations are free to cache aggressively — this is a read-only,
      low-volatility data source (calendar entries rarely change mid-analysis).
    - The production implementation (wired in ENG-1d) will query the
      building_calendar TimescaleDB table through an RLS-enforced connection.
    """

    def get_calendar_entries(
        self,
        building_id: UUID,
        start_date: datetime.date,
        end_date: datetime.date,
    ) -> list[CalendarEntry]:
        """Return all CalendarEntry rows for the building within [start, end].

        Parameters
        ----------
        building_id:
            The building whose calendar to query.
        start_date, end_date:
            Inclusive date range.  The implementation must return an entry
            for every date in this range (or the service will raise
            CalendarLookupError for any date without an entry).

        Returns
        -------
        list[CalendarEntry]
            Unordered list of entries within the requested range.
        """
        ...
