"""ENG-3c unit tests — Cold-start / low_data_quality handling.

Verifies that the service:
  1. Correctly detects when a day-type cohort has fewer than
     stl_min_history_observations readings.
  2. Emits low_data_quality=True with a non-empty reason string.
  3. Does NOT emit residual scores (residual_zscore=None, magnitude=None).
  4. Does NOT silently classify cold-start residuals as normal.
  5. Handles the transition: cohorts ABOVE the threshold get normal results;
     cohorts BELOW get low_data_quality results, both in the same window.
"""

from __future__ import annotations

import datetime

import pytest

from services.stl_detection.config import STLDetectionConfig
from services.stl_detection.models import DayType
from services.stl_detection.service import STLDetectionService
from tests.unit.services.stl_detection.conftest import (
    build_business_day_series,
    build_sufficient_business_day_series,
    make_calendar_entry,
    make_reading,
)


@pytest.mark.unit
class TestColdStartDetection:
    def test_single_day_triggers_cold_start(self) -> None:
        """24 readings < 48 minimum → cold-start for that cohort."""
        cfg = STLDetectionConfig()  # stl_min_history_observations=48
        service = STLDetectionService(config=cfg)

        readings, calendar = build_business_day_series(n_days=1)  # 24 readings
        results = service.analyse_circuit_window(readings, calendar)

        assert len(results) == 24
        for r in results:
            assert r.low_data_quality is True, (
                f"Expected low_data_quality=True for 24 observations < 48 minimum. "
                f"Got low_data_quality={r.low_data_quality}"
            )

    def test_cold_start_emits_no_residual_scores(self) -> None:
        """When low_data_quality=True, residual scores MUST be None."""
        cfg = STLDetectionConfig()
        service = STLDetectionService(config=cfg)
        readings, calendar = build_business_day_series(n_days=1)

        results = service.analyse_circuit_window(readings, calendar)

        for r in results:
            assert r.residual_zscore is None, (
                "residual_zscore must be None in cold-start — unreliable scores must not be emitted"
            )
            assert r.residual_magnitude is None, "residual_magnitude must be None in cold-start"
            assert r.stl_residual is None
            assert r.stl_trend is None
            assert r.stl_seasonal is None

    def test_cold_start_reason_is_populated(self) -> None:
        """low_data_quality_reason must be a non-empty string."""
        cfg = STLDetectionConfig()
        service = STLDetectionService(config=cfg)
        readings, calendar = build_business_day_series(n_days=1)

        results = service.analyse_circuit_window(readings, calendar)

        for r in results:
            assert r.low_data_quality_reason is not None
            assert len(r.low_data_quality_reason) > 0

    def test_cold_start_does_not_set_is_anomalous_true(self) -> None:
        """Cold-start readings must NOT be silently classified as anomalous."""
        cfg = STLDetectionConfig()
        service = STLDetectionService(config=cfg)
        readings, calendar = build_business_day_series(n_days=1)

        results = service.analyse_circuit_window(readings, calendar)

        for r in results:
            assert r.is_anomalous is False, (
                "Cold-start reading incorrectly classified as anomalous — "
                "unstable residuals must not be scored."
            )

    def test_sufficient_history_does_not_trigger_cold_start(self) -> None:
        """Above threshold → no cold-start indicator."""
        cfg = STLDetectionConfig()
        service = STLDetectionService(config=cfg)
        readings, calendar = build_sufficient_business_day_series(cfg)

        results = service.analyse_circuit_window(readings, calendar)

        low_quality = [r for r in results if r.low_data_quality]
        assert len(low_quality) == 0, (
            f"Expected no low_data_quality results for {len(readings)} observations "
            f"(>= {cfg.stl_min_history_observations} minimum). "
            f"Got {len(low_quality)} low-quality results."
        )

    def test_sufficient_history_residual_scores_populated(self) -> None:
        """With enough history, all residual score fields must be populated."""
        cfg = STLDetectionConfig()
        service = STLDetectionService(config=cfg)
        readings, calendar = build_sufficient_business_day_series(cfg)

        results = service.analyse_circuit_window(readings, calendar)

        for r in results:
            assert r.residual_zscore is not None
            assert r.residual_magnitude is not None
            assert r.stl_residual is not None

    def test_mixed_cohorts_cold_start_only_for_small_cohort(self) -> None:
        """When one cohort is below threshold and another is above,
        only the small cohort gets low_data_quality=True."""
        cfg = STLDetectionConfig()
        service = STLDetectionService(config=cfg)

        # Large business-day cohort (sufficient)
        bd_readings, bd_calendar = build_sufficient_business_day_series(cfg)

        # Small holiday cohort (1 day = 24 readings → below 48 minimum)
        hol_start = datetime.date(2026, 2, 10)
        hol_readings = []
        hol_calendar = []
        for h in range(24):
            ts = datetime.datetime(2026, 2, 10, h, 0, 0, tzinfo=datetime.UTC)
            hol_readings.append(make_reading(ts, 0.3))
        hol_calendar.append(make_calendar_entry(hol_start, DayType.HOLIDAY))

        all_readings = bd_readings + hol_readings
        all_calendar = bd_calendar + hol_calendar

        results = service.analyse_circuit_window(all_readings, all_calendar)

        bd_results = [r for r in results if r.day_type == DayType.BUSINESS_DAY]
        hol_results = [r for r in results if r.day_type == DayType.HOLIDAY]

        # Business-day: sufficient history → no cold-start
        for r in bd_results:
            assert r.low_data_quality is False, (
                f"Business-day result should not be low_data_quality: ts={r.ts}"
            )

        # Holiday: only 24 readings → cold-start
        for r in hol_results:
            assert r.low_data_quality is True, (
                f"Holiday result should be low_data_quality (24 < 48): ts={r.ts}"
            )


@pytest.mark.unit
class TestColdStartConfigurability:
    def test_custom_min_history_respected(self) -> None:
        """A custom stl_min_history_observations changes the cold-start threshold."""
        # Set threshold to 25 → 24 readings (1 day) should now trigger cold-start
        low_threshold = STLDetectionConfig(stl_min_history_observations=25)
        service = STLDetectionService(config=low_threshold)
        readings, calendar = build_business_day_series(n_days=1)  # 24 readings

        results = service.analyse_circuit_window(readings, calendar)

        for r in results:
            assert r.low_data_quality is True

    def test_threshold_of_24_allows_one_day(self) -> None:
        """With threshold=24, exactly 24 readings should NOT trigger cold-start."""
        exact_threshold = STLDetectionConfig(stl_min_history_observations=24)
        service = STLDetectionService(config=exact_threshold)
        readings, calendar = build_business_day_series(n_days=1)  # 24 readings

        results = service.analyse_circuit_window(readings, calendar)

        # With exactly the minimum, STL runs (no cold-start)
        for r in results:
            assert r.low_data_quality is False
