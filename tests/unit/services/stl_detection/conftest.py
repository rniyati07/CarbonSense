"""Shared fixtures for ENG-3c unit tests.

All fixtures are fully deterministic — no randomness.
Synthetic data is constructed from closed-form expressions (sin/cos) so
expected values can be computed analytically in each test.
"""

from __future__ import annotations

import datetime
import math
import uuid
from uuid import UUID

import pytest

from services.ingestion.models import NormalizedReading  # direct model import (avoids kafka chain)
from services.stl_detection.config import STLDetectionConfig
from services.stl_detection.models import CalendarEntry, DayType
from services.stl_detection.repository import InMemoryCalendarRepository

# ------------------------------------------------------------------ #
# Canonical IDs (shared across all stl_detection tests)
# ------------------------------------------------------------------ #

TENANT_ID: UUID = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
BUILDING_ID: UUID = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
CIRCUIT_ID: UUID = UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")


# ------------------------------------------------------------------ #
# Reading factories
# ------------------------------------------------------------------ #


def make_reading(
    ts: datetime.datetime,
    kwh: float | None,
    circuit_id: UUID = CIRCUIT_ID,
    tenant_id: UUID = TENANT_ID,
    data_quality_status: str = "pass",
) -> NormalizedReading:
    """Create a minimal NormalizedReading for test use."""
    return NormalizedReading(
        tenant_id=tenant_id,
        circuit_id=circuit_id,
        ts=ts,
        kwh=kwh,
        is_peak_hour=False,
        rolling_baseline_kwh=None,
        data_quality_status=data_quality_status,
        schema_version="normalized_reading_v1",
        source_system="csv_upload",
        ingestion_timestamp=datetime.datetime.now(tz=datetime.timezone.utc),
        normalization_version="v1.0.0",
    )


def make_calendar_entry(
    date: datetime.date,
    day_type: DayType,
    building_id: UUID = BUILDING_ID,
) -> CalendarEntry:
    return CalendarEntry(building_id=building_id, date=date, day_type=day_type)


# ------------------------------------------------------------------ #
# Synthetic time-series builders
# ------------------------------------------------------------------ #


def build_business_day_series(
    n_days: int = 4,
    base_kwh: float = 10.0,
    amplitude: float = 5.0,
    start_date: datetime.date | None = None,
) -> tuple[list[NormalizedReading], list[CalendarEntry]]:
    """Build n_days × 24 hourly business-day readings with a sinusoidal profile.

    Returns (readings, calendar_entries).
    """
    if start_date is None:
        start_date = datetime.date(2026, 1, 5)  # Monday

    readings: list[NormalizedReading] = []
    calendar_entries: list[CalendarEntry] = []

    for day_offset in range(n_days):
        current_date = start_date + datetime.timedelta(days=day_offset)
        calendar_entries.append(
            make_calendar_entry(current_date, DayType.BUSINESS_DAY)
        )
        for hour in range(24):
            ts = datetime.datetime(
                current_date.year, current_date.month, current_date.day,
                hour, 0, 0, tzinfo=datetime.timezone.utc,
            )
            kwh = base_kwh + amplitude * math.sin(math.pi * hour / 23)
            readings.append(make_reading(ts, round(kwh, 6)))

    return readings, calendar_entries


def build_holiday_series(
    n_days: int = 4,
    standby_kwh: float = 0.3,
    start_date: datetime.date | None = None,
) -> tuple[list[NormalizedReading], list[CalendarEntry]]:
    """Build n_days × 24 hourly holiday readings with near-zero consumption."""
    if start_date is None:
        start_date = datetime.date(2026, 3, 25)

    readings: list[NormalizedReading] = []
    calendar_entries: list[CalendarEntry] = []

    for day_offset in range(n_days):
        current_date = start_date + datetime.timedelta(days=day_offset)
        calendar_entries.append(
            make_calendar_entry(current_date, DayType.HOLIDAY)
        )
        for hour in range(24):
            ts = datetime.datetime(
                current_date.year, current_date.month, current_date.day,
                hour, 0, 0, tzinfo=datetime.timezone.utc,
            )
            readings.append(make_reading(ts, standby_kwh))

    return readings, calendar_entries


def build_sufficient_business_day_series(
    config: STLDetectionConfig | None = None,
) -> tuple[list[NormalizedReading], list[CalendarEntry]]:
    """Build a series guaranteed to exceed stl_min_history_observations."""
    cfg = config or STLDetectionConfig()
    n_days = (cfg.stl_min_history_observations // 24) + 3
    return build_business_day_series(n_days=n_days)


# ------------------------------------------------------------------ #
# Pytest fixtures
# ------------------------------------------------------------------ #


@pytest.fixture()
def stl_config() -> STLDetectionConfig:
    return STLDetectionConfig()


@pytest.fixture()
def empty_calendar_repo() -> InMemoryCalendarRepository:
    return InMemoryCalendarRepository()


@pytest.fixture()
def sufficient_business_day_data(
    stl_config: STLDetectionConfig,
) -> tuple[list[NormalizedReading], list[CalendarEntry]]:
    """Readings + calendar for a series long enough to pass cold-start check."""
    return build_sufficient_business_day_series(stl_config)


@pytest.fixture()
def short_series_data() -> tuple[list[NormalizedReading], list[CalendarEntry]]:
    """Only 24 readings — below the 48-observation cold-start threshold."""
    return build_business_day_series(n_days=1)
