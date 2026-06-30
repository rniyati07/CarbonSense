"""ENG-3c unit tests — STLDetectionService.

Tests the orchestration layer: calendar join, cohort grouping,
result ordering, error propagation.
"""

from __future__ import annotations

import datetime
import math

import pytest

from services.stl_detection.config import STLDetectionConfig
from services.stl_detection.exceptions import CalendarLookupError
from services.stl_detection.models import DayType
from services.stl_detection.repository import InMemoryCalendarRepository
from services.stl_detection.service import STLDetectionService
from tests.unit.services.stl_detection.conftest import (
    BUILDING_ID,
    CIRCUIT_ID,
    TENANT_ID,
    build_business_day_series,
    build_holiday_series,
    build_sufficient_business_day_series,
    make_calendar_entry,
    make_reading,
)


@pytest.mark.unit
class TestAnalyseCircuitWindowBasic:
    def test_empty_readings_returns_empty_list(self) -> None:
        service = STLDetectionService()
        results = service.analyse_circuit_window([], [])
        assert results == []

    def test_returns_one_result_per_reading(self) -> None:
        cfg = STLDetectionConfig()
        service = STLDetectionService(config=cfg)
        readings, calendar = build_sufficient_business_day_series(cfg)
        results = service.analyse_circuit_window(readings, calendar)
        assert len(results) == len(readings)

    def test_results_sorted_by_timestamp_ascending(self) -> None:
        cfg = STLDetectionConfig()
        service = STLDetectionService(config=cfg)
        # Pass readings in reverse order — results must come back sorted
        readings, calendar = build_sufficient_business_day_series(cfg)
        readings_reversed = list(reversed(readings))
        results = service.analyse_circuit_window(readings_reversed, calendar)
        timestamps = [r.ts for r in results]
        assert timestamps == sorted(timestamps)

    def test_all_results_have_tenant_and_circuit_id(self) -> None:
        cfg = STLDetectionConfig()
        service = STLDetectionService(config=cfg)
        readings, calendar = build_sufficient_business_day_series(cfg)
        results = service.analyse_circuit_window(readings, calendar)
        for r in results:
            assert r.tenant_id == TENANT_ID
            assert r.circuit_id == CIRCUIT_ID

    def test_day_type_matches_calendar_entry(self) -> None:
        cfg = STLDetectionConfig()
        service = STLDetectionService(config=cfg)
        readings, calendar = build_sufficient_business_day_series(cfg)
        results = service.analyse_circuit_window(readings, calendar)
        for r in results:
            assert r.day_type == DayType.BUSINESS_DAY


@pytest.mark.unit
class TestAnalyseCircuitWindowCalendarEnforcement:
    def test_raises_calendar_lookup_error_for_missing_date(self) -> None:
        """A reading with no CalendarEntry must raise CalendarLookupError.

        The service must never silently assign a default day_type.
        """
        cfg = STLDetectionConfig()
        service = STLDetectionService(config=cfg)
        readings, calendar = build_sufficient_business_day_series(cfg)

        # Remove one calendar entry to trigger the error
        incomplete_calendar = calendar[1:]  # drop first day

        with pytest.raises(CalendarLookupError) as exc_info:
            service.analyse_circuit_window(readings, incomplete_calendar)

        assert exc_info.value.building_id is not None

    def test_no_silent_fallback_day_type(self) -> None:
        """Verify that the service doesn't quietly substitute business_day
        when the calendar is missing an entry."""
        cfg = STLDetectionConfig()
        service = STLDetectionService(config=cfg)

        # Two-day series, only one calendar entry supplied
        readings, calendar = build_business_day_series(n_days=2)
        partial_calendar = [calendar[0]]  # only first day

        with pytest.raises(CalendarLookupError):
            service.analyse_circuit_window(readings, partial_calendar)


@pytest.mark.unit
class TestAnalyseCircuitWindowCohortSeparation:
    def test_business_day_and_weekend_cohorts_separate(self) -> None:
        """Business-day and weekend readings must be decomposed independently.

        Both cohorts must appear in the output with their correct day_type.
        """
        cfg = STLDetectionConfig()
        service = STLDetectionService(config=cfg)

        # Business-day readings
        bd_readings, bd_calendar = build_sufficient_business_day_series(cfg)
        # Weekend readings (8 days = 192 readings)
        we_start = datetime.date(2026, 2, 7)  # Saturday
        we_readings = []
        we_calendar = []
        for d in range(8):
            date = we_start + datetime.timedelta(days=d)
            we_calendar.append(make_calendar_entry(date, DayType.WEEKEND))
            for h in range(24):
                ts = datetime.datetime(
                    date.year,
                    date.month,
                    date.day,
                    h,
                    0,
                    0,
                    tzinfo=datetime.UTC,
                )
                we_readings.append(make_reading(ts, 3.0 + math.sin(h)))

        all_readings = bd_readings + we_readings
        all_calendar = bd_calendar + we_calendar

        results = service.analyse_circuit_window(all_readings, all_calendar)

        business_results = [r for r in results if r.day_type == DayType.BUSINESS_DAY]
        weekend_results = [r for r in results if r.day_type == DayType.WEEKEND]

        assert len(business_results) == len(bd_readings)
        assert len(weekend_results) == len(we_readings)

    def test_holiday_cohort_separate_from_business_day(self) -> None:
        cfg = STLDetectionConfig()
        service = STLDetectionService(config=cfg)

        bd_readings, bd_calendar = build_sufficient_business_day_series(cfg)
        hol_readings, hol_calendar = build_holiday_series(n_days=3)

        all_readings = bd_readings + hol_readings
        all_calendar = bd_calendar + hol_calendar

        results = service.analyse_circuit_window(all_readings, all_calendar)

        hol_results = [r for r in results if r.day_type == DayType.HOLIDAY]
        assert len(hol_results) == len(hol_readings)
        for r in hol_results:
            assert r.day_type == DayType.HOLIDAY


@pytest.mark.unit
class TestAnalyseCircuitWindowWithRepo:
    def test_raises_when_no_calendar_repo_injected(self) -> None:
        service = STLDetectionService()  # no repo
        with pytest.raises(RuntimeError, match="CalendarRepository"):
            service.analyse_circuit_window_with_repo([], BUILDING_ID)

    def test_fetches_calendar_from_repo(self) -> None:
        cfg = STLDetectionConfig()
        readings, calendar_entries = build_sufficient_business_day_series(cfg)

        repo = InMemoryCalendarRepository(calendar_entries)
        service = STLDetectionService(config=cfg, calendar_repo=repo)

        results = service.analyse_circuit_window_with_repo(readings, BUILDING_ID)
        assert len(results) == len(readings)


@pytest.mark.unit
class TestBuildWindowResult:
    def test_window_result_summary_counts_correct(self) -> None:
        cfg = STLDetectionConfig()
        service = STLDetectionService(config=cfg)
        readings, calendar = build_sufficient_business_day_series(cfg)

        window = service.build_window_result(
            tenant_id=TENANT_ID,
            building_id=BUILDING_ID,
            circuit_id=CIRCUIT_ID,
            readings=readings,
            calendar_entries=calendar,
        )
        assert window.total_readings == len(readings)
        assert window.tenant_id == TENANT_ID
        assert window.building_id == BUILDING_ID
        assert window.circuit_id == CIRCUIT_ID
        assert window.window_start <= window.window_end
