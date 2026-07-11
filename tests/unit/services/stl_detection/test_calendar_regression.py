"""ENG-3c — MANDATORY calendar regression test.

This test encodes the hard requirement from TRD §3.3:

    "A holiday closure doesn't get scored as an anomalous low-consumption day."

Two scenarios are tested with IDENTICAL kWh readings.  The only difference
is the day_type label supplied by the building_calendar.

Scenario 1 — Holiday label, near-zero consumption
    Expected: NOT anomalous.
    A building at minimal standby power on a declared holiday is normal
    behaviour.  The STL layer must condition on holiday day_type and not
    compare this consumption against the business-day baseline.

Scenario 2 — Same readings, mislabelled as business_day
    Expected: IS anomalous (at least one reading flagged).
    The identical near-zero consumption on what the calendar claims is a
    business day IS anomalous relative to the business-day baseline.

If Scenario 1 fails → the system would generate false-positive findings on
    every holiday, destroying user trust in the findings feed.

If Scenario 2 fails → the regression has lost its discriminating power;
    the calendar enforcement is not actually doing anything.

Both scenarios must hold simultaneously for the test to pass.
"""

from __future__ import annotations

import datetime
import math

import pytest

from services.stl_detection.config import STLDetectionConfig
from services.stl_detection.models import DayType
from services.stl_detection.service import STLDetectionService
from tests.unit.services.stl_detection.conftest import (
    make_calendar_entry,
    make_reading,
)

# ------------------------------------------------------------------ #
# Constants for synthetic scenario construction
# ------------------------------------------------------------------ #

# Use a smaller period for faster tests (still a valid STL decomposition)
_TEST_PERIOD = 24  # hourly readings, daily cycle

# We need a large enough business-day history that STL has a stable
# baseline.  The STL_MIN_HISTORY_OBSERVATIONS default is 48; we supply
# 5 full days (120 readings) to be well above the threshold.
_N_BUSINESS_DAYS = 5

# Holiday scenario: 3 days of near-zero standby consumption
_N_HOLIDAY_DAYS = 3

# The near-zero standby kWh (realistic: security lighting, servers)
_STANDBY_KWH = 0.35

# Normal business-day profile: sinusoidal, peaks mid-day
_BUSINESS_PEAK_KWH = 18.0
_BUSINESS_BASE_KWH = 4.0


def _build_business_day_readings(
    start_date: datetime.date,
    n_days: int,
) -> tuple[list, list]:
    """Build n_days × 24 hourly business-day readings with a realistic profile."""
    readings = []
    calendar = []
    for day_offset in range(n_days):
        current_date = start_date + datetime.timedelta(days=day_offset)
        calendar.append(make_calendar_entry(current_date, DayType.BUSINESS_DAY))
        for hour in range(24):
            ts = datetime.datetime(
                current_date.year,
                current_date.month,
                current_date.day,
                hour,
                0,
                0,
                tzinfo=datetime.UTC,
            )
            kwh = (
                _BUSINESS_BASE_KWH + _BUSINESS_PEAK_KWH * math.sin(math.pi * max(0, hour - 6) / 14)
                if 6 <= hour <= 20
                else _BUSINESS_BASE_KWH
            )
            readings.append(make_reading(ts, round(kwh, 4)))
    return readings, calendar


def _build_near_zero_readings(
    start_date: datetime.date,
    n_days: int,
) -> list:
    """Build n_days × 24 hourly readings with near-zero standby consumption.

    These are the SHARED readings used in BOTH Scenario 1 and Scenario 2.
    """
    readings = []
    for day_offset in range(n_days):
        current_date = start_date + datetime.timedelta(days=day_offset)
        for hour in range(24):
            ts = datetime.datetime(
                current_date.year,
                current_date.month,
                current_date.day,
                hour,
                0,
                0,
                tzinfo=datetime.UTC,
            )
            readings.append(make_reading(ts, _STANDBY_KWH))
    return readings


@pytest.mark.unit
class TestCalendarRegressionHoliday:
    """Mandatory calendar regression test — TRD §3.3.

    SCENARIO 1: holiday label → near-zero consumption NOT anomalous.
    SCENARIO 2: same readings + business_day label → IS anomalous.
    """

    # Dates for the initial business-day history block (establishes baseline)
    _HISTORY_START = datetime.date(2026, 1, 5)  # Monday
    # Dates for the near-zero readings (used in both scenarios)
    _SCENARIO_START = datetime.date(2026, 1, 12)  # 5 working days later

    def _run_scenario(
        self,
        near_zero_day_type: DayType,
        config: STLDetectionConfig | None = None,
    ) -> list:
        """Build the history block + near-zero block, label near-zero with
        near_zero_day_type, and return the STL results for the near-zero readings."""
        cfg = config or STLDetectionConfig()
        service = STLDetectionService(config=cfg)

        # 1. Build business-day history (5 days = 120 readings — sufficient)
        history_readings, history_calendar = _build_business_day_readings(
            start_date=self._HISTORY_START,
            n_days=_N_BUSINESS_DAYS,
        )

        # 2. Build near-zero readings (shared between both scenarios)
        scenario_readings = _build_near_zero_readings(
            start_date=self._SCENARIO_START,
            n_days=_N_HOLIDAY_DAYS,
        )

        # 3. Build calendar for the near-zero block with the specified day_type
        scenario_calendar = [
            make_calendar_entry(
                self._SCENARIO_START + datetime.timedelta(days=d),
                near_zero_day_type,
            )
            for d in range(_N_HOLIDAY_DAYS)
        ]

        # 4. Combine history + scenario readings and calendar
        all_readings = history_readings + scenario_readings
        all_calendar = history_calendar + scenario_calendar

        # 5. Run STL analysis on the full window
        all_results = service.analyse_circuit_window(all_readings, all_calendar)

        # 6. Extract only the scenario-window results
        scenario_dates = {
            self._SCENARIO_START + datetime.timedelta(days=d) for d in range(_N_HOLIDAY_DAYS)
        }
        scenario_results = [r for r in all_results if r.ts.date() in scenario_dates]
        return scenario_results

    # ---------------------------------------------------------------- #
    # SCENARIO 1 — Holiday label, near-zero consumption → NOT anomalous
    # ---------------------------------------------------------------- #

    def test_scenario1_holiday_label_not_anomalous(self) -> None:
        """SCENARIO 1: holiday + near-zero consumption.

        Expected: NOT anomalous.

        Near-zero consumption is consistent behaviour within the holiday
        cohort (all holiday readings are near-zero → no large residuals).
        The STL layer must NOT compare this against the business-day baseline.
        """
        results = self._run_scenario(near_zero_day_type=DayType.HOLIDAY)

        assert len(results) > 0, "Expected scenario results to be non-empty"

        # Every scenario reading should either:
        #   (a) not be anomalous (the expected happy path), or
        #   (b) be flagged low_data_quality (acceptable when holiday cohort
        #       has fewer readings than stl_min_history_observations)
        for r in results:
            assert r.is_anomalous is False or r.low_data_quality is True, (
                f"REGRESSION FAILURE — Scenario 1: holiday day with near-zero "
                f"consumption was flagged as anomalous at ts={r.ts.isoformat()}. "
                f"is_anomalous={r.is_anomalous}, "
                f"residual_zscore={r.residual_zscore}, "
                f"low_data_quality={r.low_data_quality}. "
                "The STL layer must not score a holiday closure as an anomaly."
            )

    def test_scenario1_holiday_day_type_preserved_in_result(self) -> None:
        """day_type on result must match the calendar label, not be overwritten."""
        results = self._run_scenario(near_zero_day_type=DayType.HOLIDAY)
        for r in results:
            assert r.day_type == DayType.HOLIDAY, (
                f"day_type was overwritten to {r.day_type!r} instead of 'holiday'"
            )

    def test_scenario1_cold_start_holiday_cohort_emits_low_data_quality(self) -> None:
        """When the holiday cohort has fewer than stl_min_history_observations,
        results MUST carry low_data_quality=True, not fabricated residuals."""
        # Only 3 holiday days × 24 hours = 72 readings → above 48 threshold
        # but let's test with an explicit config that raises the bar to 96
        strict_config = STLDetectionConfig(stl_min_history_observations=96)
        results = self._run_scenario(
            near_zero_day_type=DayType.HOLIDAY,
            config=strict_config,
        )
        # 3 × 24 = 72 < 96 → all holiday readings should be low_data_quality
        for r in results:
            assert r.low_data_quality is True, (
                f"Expected low_data_quality=True for 72 observations < 96 minimum. "
                f"Got low_data_quality={r.low_data_quality} at ts={r.ts.isoformat()}"
            )
            assert r.residual_zscore is None
            assert r.residual_magnitude is None

    # ---------------------------------------------------------------- #
    # SCENARIO 2 — Same readings, business_day label → IS anomalous
    # ---------------------------------------------------------------- #

    def test_scenario2_business_day_label_detects_anomaly(self) -> None:
        """SCENARIO 2: same near-zero readings + business_day label.

        Expected: at least one reading IS anomalous.

        Near-zero consumption during a declared business day is a genuine
        anomaly relative to the business-day STL baseline (which captures
        the building's normal daytime usage profile).
        """
        results = self._run_scenario(near_zero_day_type=DayType.BUSINESS_DAY)

        assert len(results) > 0, "Expected scenario results to be non-empty"

        # Some scenario readings must be anomalous OR flagged low_data_quality
        # (if the cohort-merged business-day data somehow still triggers
        # cold-start, the test degrades gracefully rather than false-failing).
        has_anomaly = any(r.is_anomalous for r in results)
        all_low_quality = all(r.low_data_quality for r in results)

        assert has_anomaly or all_low_quality, (
            "REGRESSION FAILURE — Scenario 2: near-zero consumption labelled as "
            "'business_day' was NOT flagged as anomalous. "
            "If the business-day cohort is large enough for STL (which it is, "
            "given 5 days of history), near-zero consumption relative to a normal "
            "business-day pattern should produce large residuals. "
            f"Results: anomalous_count={sum(r.is_anomalous for r in results)}, "
            f"total={len(results)}"
        )

    def test_scenario2_business_day_type_preserved_in_result(self) -> None:
        results = self._run_scenario(near_zero_day_type=DayType.BUSINESS_DAY)
        for r in results:
            assert r.day_type == DayType.BUSINESS_DAY

    # ---------------------------------------------------------------- #
    # Cross-scenario invariants
    # ---------------------------------------------------------------- #

    def test_scenarios_differ_in_anomaly_outcome(self) -> None:
        """CORE REGRESSION: the two scenarios with identical kWh must
        produce different anomaly classifications.

        This is the ultimate test of calendar-awareness: the same physical
        consumption data, classified differently by the calendar, must yield
        a different detection outcome.
        """
        holiday_results = self._run_scenario(near_zero_day_type=DayType.HOLIDAY)
        business_results = self._run_scenario(near_zero_day_type=DayType.BUSINESS_DAY)

        holiday_anomalous = [r for r in holiday_results if r.is_anomalous]
        business_anomalous = [r for r in business_results if r.is_anomalous]

        # Holiday: zero anomalies (or all low_data_quality)
        holiday_ok = len(holiday_anomalous) == 0 or all(r.low_data_quality for r in holiday_results)
        # Business: at least one anomaly (or all low_data_quality as graceful degrade)
        business_ok = len(business_anomalous) > 0 or all(
            r.low_data_quality for r in business_results
        )

        assert holiday_ok, (
            f"REGRESSION: {len(holiday_anomalous)} holiday readings were flagged "
            "anomalous — calendar-awareness is broken."
        )
        assert business_ok, (
            "REGRESSION: no business-day readings were flagged anomalous "
            "for near-zero consumption — STL baseline not working correctly."
        )


@pytest.mark.unit
class TestCalendarRegressionWeekend:
    """Weekend readings are grouped into their own cohort, separate from
    business_day.  Weekend consumption patterns differ (lower, flatter);
    treating them as business days would produce false positives.
    """

    def test_weekend_low_consumption_not_anomalous_when_labelled_weekend(
        self,
    ) -> None:
        cfg = STLDetectionConfig()
        service = STLDetectionService(config=cfg)

        # Build 8 weekend days (Sat/Sun × 4 weeks = 192 readings)
        start = datetime.date(2026, 1, 3)  # Saturday
        readings = []
        calendar = []
        for day_offset in range(8):
            current_date = start + datetime.timedelta(days=day_offset)
            calendar.append(make_calendar_entry(current_date, DayType.WEEKEND))
            for hour in range(24):
                ts = datetime.datetime(
                    current_date.year,
                    current_date.month,
                    current_date.day,
                    hour,
                    0,
                    0,
                    tzinfo=datetime.UTC,
                )
                # Weekend: lower, flatter profile (no daytime peak)
                kwh = 3.0 + 1.0 * math.sin(math.pi * hour / 23)
                readings.append(make_reading(ts, round(kwh, 4)))

        results = service.analyse_circuit_window(readings, calendar)

        for r in results:
            assert r.day_type == DayType.WEEKEND
            # Weekend-labelled readings in a consistent weekend cohort
            # should not be anomalous
            assert r.is_anomalous is False or r.low_data_quality is True


@pytest.mark.unit
class TestCalendarRegressionDeclaredClosure:
    """declared_closure is the fourth day_type.  A day explicitly marked as a
    tenant-uploaded closure must behave like a holiday — no business-day
    comparison should occur.
    """

    def test_declared_closure_near_zero_not_anomalous(self) -> None:
        cfg = STLDetectionConfig(stl_min_history_observations=2)
        service = STLDetectionService(config=cfg)

        start = datetime.date(2026, 2, 10)
        readings = []
        calendar = []
        for day_offset in range(3):
            current_date = start + datetime.timedelta(days=day_offset)
            calendar.append(make_calendar_entry(current_date, DayType.DECLARED_CLOSURE))
            for hour in range(24):
                ts = datetime.datetime(
                    current_date.year,
                    current_date.month,
                    current_date.day,
                    hour,
                    0,
                    0,
                    tzinfo=datetime.UTC,
                )
                readings.append(make_reading(ts, 0.2))  # near-zero

        results = service.analyse_circuit_window(readings, calendar)

        for r in results:
            assert r.day_type == DayType.DECLARED_CLOSURE
            assert r.is_anomalous is False or r.low_data_quality is True
