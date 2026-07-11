"""ENG-3c — STL Residual Detection exceptions.

Exception hierarchy for the stl_detection service.  All exceptions are
derived from STLDetectionError so callers can catch the base type and
handle the service's errors as a family.

Design notes
------------
InsufficientHistoryError is raised INTERNALLY by decomposition.py when a
day-type cohort has fewer readings than STL_MIN_HISTORY_OBSERVATIONS.
service.py catches it and converts it to a low_data_quality=True flag on
every affected STLResidualResult.  It is NEVER propagated to callers as an
unhandled exception — callers see a populated result list, not an exception.

CalendarLookupError is raised when a reading timestamp cannot be matched to
a CalendarEntry.  The STL service has a hard requirement (TRD §3.3) that
every reading must carry an explicit day_type classification; silently
defaulting to a fallback day_type would violate the calendar-awareness
guarantee.  Callers must supply a complete calendar for the analysis window.
"""

from __future__ import annotations


class STLDetectionError(Exception):
    """Base exception for the STL Residual Detection service."""


class InsufficientHistoryError(STLDetectionError):
    """Raised when a day-type cohort has too few observations for stable STL.

    Caught by STLDetectionService and converted to low_data_quality outputs.
    Never propagated to external callers.
    """

    def __init__(self, day_type: str, n_observations: int, minimum_required: int) -> None:
        self.day_type = day_type
        self.n_observations = n_observations
        self.minimum_required = minimum_required
        super().__init__(
            f"Insufficient history for STL decomposition: day_type={day_type!r}, "
            f"n_observations={n_observations} < minimum_required={minimum_required}. "
            "Emitting low_data_quality indicator instead of residual scores."
        )


class CalendarLookupError(STLDetectionError):
    """Raised when a reading date cannot be matched to a CalendarEntry.

    The STL layer has a hard calendar-awareness requirement (TRD §3.3).
    Every reading must have an explicit day_type — no silent fallback.
    Callers must supply a CalendarEntry for every date in the analysis window.
    """

    def __init__(self, missing_date: str, building_id: str) -> None:
        self.missing_date = missing_date
        self.building_id = building_id
        super().__init__(
            f"No CalendarEntry found for date={missing_date!r} "
            f"building_id={building_id!r}. "
            "Provide a complete building_calendar for the analysis window."
        )
