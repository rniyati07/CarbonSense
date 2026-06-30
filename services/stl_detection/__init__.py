"""ENG-3c — STL Residual Detection service.

Public API
----------
STLDetectionService
    Calendar-aware orchestrator.  Accepts NormalizedReading + CalendarEntry
    lists, groups by day_type, decomposes each cohort independently with
    statsmodels STL, and returns per-reading STLResidualResult objects.

STLDetectionConfig
    All thresholds and STL parameters.  Centralised here; no magic numbers
    in service or test code.

CalendarRepository (Protocol)
    Inject a CalendarRepository to let the service fetch calendar entries
    automatically.  InMemoryCalendarRepository is the test implementation.

Models
------
CalendarEntry, DayType, STLResidualResult, STLWindowResult
    See services.stl_detection.models for field-level documentation.

Exceptions
----------
STLDetectionError → InsufficientHistoryError, CalendarLookupError
    See services.stl_detection.exceptions.

Architecture notes
------------------
- STL models are NEVER persisted.  No MLflow, no sklearn.
- No confidence values produced (belongs to ENG-3f).
- Output is fully reproducible for identical inputs.
- This service remains functional when every ML component is offline.
"""

from services.stl_detection.config import STLDetectionConfig
from services.stl_detection.exceptions import (
    CalendarLookupError,
    InsufficientHistoryError,
    STLDetectionError,
)
from services.stl_detection.interfaces import CalendarRepository
from services.stl_detection.models import (
    CalendarEntry,
    DayType,
    STLResidualResult,
    STLWindowResult,
)
from services.stl_detection.repository import InMemoryCalendarRepository
from services.stl_detection.service import STLDetectionService

__all__ = [
    # Config
    "STLDetectionConfig",
    # Service
    "STLDetectionService",
    # Interfaces
    "CalendarRepository",
    # Repository implementations
    "InMemoryCalendarRepository",
    # Models
    "CalendarEntry",
    "DayType",
    "STLResidualResult",
    "STLWindowResult",
    # Exceptions
    "STLDetectionError",
    "InsufficientHistoryError",
    "CalendarLookupError",
]
