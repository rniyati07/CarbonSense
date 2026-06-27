"""ENG-3c integration test — Full STL detection pipeline.

Validates the end-to-end flow:

    NormalizedReading list (synthetic, 3-month window)
        ↓ calendar-aware STL decomposition
        ↓ per-reading residual z-score generation
        ↓ STLResidualResult list
        ↓ FeatureSetV1STLFields construction

Test scenarios:
    1. Happy path: business-day readings with a synthetic injected spike
       are correctly decomposed; spike is flagged anomalous.
    2. Holiday readings in the same window are NOT flagged anomalous.
    3. Cold-start cohort (short holiday cohort) emits low_data_quality.
    4. All results can be converted to FeatureSetV1STLFields without error.
    5. Pipeline is reproducible: running twice produces identical results.

Does NOT require any external services (database, Kafka, MLflow).
Uses InMemoryCalendarRepository for calendar lookups.
"""

from __future__ import annotations

import datetime
import math

import pytest

from models.feature_store.feature_set_v1 import FeatureSetV1STLFields
from services.stl_detection.config import STLDetectionConfig
from services.stl_detection.models import DayType, STLResidualResult
from services.stl_detection.repository import InMemoryCalendarRepository
from services.stl_detection.service import STLDetectionService
from tests.unit.services.stl_detection.conftest import (
    BUILDING_ID,
    CIRCUIT_ID,
    TENANT_ID,
    make_calendar_entry,
    make_reading,
)

pytestmark = pytest.mark.integration

# ------------------------------------------------------------------ #
# Fixture constants
# ------------------------------------------------------------------ #

_BD_START = datetime.date(2026, 1, 5)       # Monday — business-day history start
_HOL_START = datetime.date(2026, 3, 30)     # Holiday block start
_SPIKE_DATE = datetime.date(2026, 3, 3)     # Date of injected anomaly
_SPIKE_HOUR = 14                            # Hour of injected anomaly
_SPIKE_MULTIPLIER = 4.0                     # Factor above normal

_N_BUSINESS_DAYS = 60   # ~3 months Mon–Fri
_N_HOLIDAY_DAYS = 4     # 4 holiday days (96 readings → above 48 threshold)

_BUSINESS_BASE_KWH = 5.0
_BUSINESS_AMPLITUDE = 8.0
_STANDBY_KWH = 0.3


# ------------------------------------------------------------------ #
# Synthetic data builders
# ------------------------------------------------------------------ #


def _build_full_window() -> tuple[list, list]:
    """Build 60 business days + 4 holiday days with an injected spike.

    Returns (all_readings, all_calendar_entries).
    """
    readings = []
    calendar_entries = []

    # ---- Business days ----
    days_added = 0
    day_offset = 0
    while days_added < _N_BUSINESS_DAYS:
        current_date = _BD_START + datetime.timedelta(days=day_offset)
        day_offset += 1
        if current_date.weekday() >= 5:  # skip Saturday/Sunday
            continue

        calendar_entries.append(
            make_calendar_entry(current_date, DayType.BUSINESS_DAY)
        )
        for hour in range(24):
            ts = datetime.datetime(
                current_date.year, current_date.month, current_date.day,
                hour, 0, 0, tzinfo=datetime.timezone.utc,
            )
            base = _BUSINESS_BASE_KWH + _BUSINESS_AMPLITUDE * math.sin(
                math.pi * max(0, hour - 7) / 11
            ) if 7 <= hour <= 18 else _BUSINESS_BASE_KWH

            # Inject spike on the specific date and hour
            if current_date == _SPIKE_DATE and hour == _SPIKE_HOUR:
                kwh = base * _SPIKE_MULTIPLIER
            else:
                kwh = base

            readings.append(make_reading(ts, round(kwh, 4)))
        days_added += 1

    # ---- Holiday days ----
    for d in range(_N_HOLIDAY_DAYS):
        current_date = _HOL_START + datetime.timedelta(days=d)
        calendar_entries.append(
            make_calendar_entry(current_date, DayType.HOLIDAY)
        )
        for hour in range(24):
            ts = datetime.datetime(
                current_date.year, current_date.month, current_date.day,
                hour, 0, 0, tzinfo=datetime.timezone.utc,
            )
            readings.append(make_reading(ts, _STANDBY_KWH))

    return readings, calendar_entries


# ------------------------------------------------------------------ #
# Integration tests
# ------------------------------------------------------------------ #


class TestSTLPipelineHappyPath:
    """Normal operation: sufficient history, mixed day types."""

    def test_pipeline_returns_result_per_reading(self) -> None:
        cfg = STLDetectionConfig()
        service = STLDetectionService(config=cfg)
        readings, calendar = _build_full_window()

        results = service.analyse_circuit_window(readings, calendar)

        assert len(results) == len(readings), (
            f"Expected {len(readings)} results, got {len(results)}"
        )

    def test_business_day_residual_fields_populated(self) -> None:
        cfg = STLDetectionConfig()
        service = STLDetectionService(config=cfg)
        readings, calendar = _build_full_window()

        results = service.analyse_circuit_window(readings, calendar)

        bd_results = [r for r in results if r.day_type == DayType.BUSINESS_DAY]
        assert len(bd_results) > 0

        non_quality = [r for r in bd_results if not r.low_data_quality]
        for r in non_quality:
            assert r.residual_zscore is not None, (
                f"residual_zscore should be populated for non-cold-start result: ts={r.ts}"
            )
            assert r.residual_magnitude is not None
            assert r.stl_residual is not None

    def test_injected_spike_detected_as_anomalous(self) -> None:
        """The 4× spike on _SPIKE_DATE at _SPIKE_HOUR must be flagged."""
        cfg = STLDetectionConfig()
        service = STLDetectionService(config=cfg)
        readings, calendar = _build_full_window()

        results = service.analyse_circuit_window(readings, calendar)

        spike_results = [
            r for r in results
            if r.ts.date() == _SPIKE_DATE and r.ts.hour == _SPIKE_HOUR
        ]
        assert len(spike_results) == 1, "Expected exactly one spike result"
        spike = spike_results[0]

        assert not spike.low_data_quality, "Spike result should not be cold-start"
        assert spike.is_anomalous is True, (
            f"Expected spike at {_SPIKE_DATE} hour {_SPIKE_HOUR} to be flagged "
            f"anomalous. residual_zscore={spike.residual_zscore}, "
            f"threshold={cfg.residual_zscore_anomaly_threshold}"
        )


class TestSTLPipelineHolidayNotAnomalous:
    """Holiday readings with near-zero consumption must not be anomalous."""

    def test_holiday_readings_not_anomalous(self) -> None:
        cfg = STLDetectionConfig()
        service = STLDetectionService(config=cfg)
        readings, calendar = _build_full_window()

        results = service.analyse_circuit_window(readings, calendar)

        holiday_results = [r for r in results if r.day_type == DayType.HOLIDAY]
        assert len(holiday_results) == _N_HOLIDAY_DAYS * 24

        for r in holiday_results:
            assert r.is_anomalous is False or r.low_data_quality is True, (
                f"Holiday reading at {r.ts.isoformat()} was flagged anomalous. "
                f"residual_zscore={r.residual_zscore}"
            )

    def test_holiday_day_type_in_results(self) -> None:
        cfg = STLDetectionConfig()
        service = STLDetectionService(config=cfg)
        readings, calendar = _build_full_window()

        results = service.analyse_circuit_window(readings, calendar)

        holiday_results = [r for r in results if r.day_type == DayType.HOLIDAY]
        for r in holiday_results:
            assert r.day_type == DayType.HOLIDAY


class TestSTLPipelineColdStart:
    """Cold-start cohorts emit low_data_quality — never fabricated scores."""

    def test_short_holiday_cohort_triggers_cold_start(self) -> None:
        """If the holiday cohort has < stl_min_history_observations readings,
        all holiday results must be low_data_quality."""
        # Threshold = 96 (4 × 24), but we supply exactly 4 days → 96 ≥ 96: passes.
        # Use threshold = 120 to force cold-start.
        strict_cfg = STLDetectionConfig(stl_min_history_observations=120)
        service = STLDetectionService(config=strict_cfg)
        readings, calendar = _build_full_window()

        results = service.analyse_circuit_window(readings, calendar)

        holiday_results = [r for r in results if r.day_type == DayType.HOLIDAY]
        # 4 days × 24 hours = 96 < 120 minimum → cold-start
        for r in holiday_results:
            assert r.low_data_quality is True
            assert r.residual_zscore is None


class TestSTLPipelineFeatureOutput:
    """All STL results must convert to FeatureSetV1STLFields without error."""

    def test_feature_construction_from_every_result(self) -> None:
        cfg = STLDetectionConfig()
        service = STLDetectionService(config=cfg)
        readings, calendar = _build_full_window()

        results = service.analyse_circuit_window(readings, calendar)

        for stl_result in results:
            feature = FeatureSetV1STLFields.from_stl_result(stl_result)
            assert feature.day_type in {
                "business_day", "weekend", "holiday", "declared_closure"
            }

    def test_spike_result_has_high_zscore_in_feature(self) -> None:
        """The spike's feature row must carry a high residual_zscore."""
        cfg = STLDetectionConfig()
        service = STLDetectionService(config=cfg)
        readings, calendar = _build_full_window()

        results = service.analyse_circuit_window(readings, calendar)

        spike = next(
            (r for r in results
             if r.ts.date() == _SPIKE_DATE and r.ts.hour == _SPIKE_HOUR),
            None,
        )
        assert spike is not None
        feature = FeatureSetV1STLFields.from_stl_result(spike)

        if not feature.low_data_quality:
            assert feature.residual_zscore is not None
            assert abs(feature.residual_zscore) > cfg.residual_zscore_anomaly_threshold


class TestSTLPipelineReproducibility:
    """Running the pipeline twice with identical inputs must produce identical results."""

    def test_same_inputs_same_residuals(self) -> None:
        cfg = STLDetectionConfig()
        service = STLDetectionService(config=cfg)
        readings, calendar = _build_full_window()

        results_a = service.analyse_circuit_window(readings, calendar)
        results_b = service.analyse_circuit_window(readings, calendar)

        assert len(results_a) == len(results_b)
        for a, b in zip(results_a, results_b):
            assert a.ts == b.ts
            assert a.is_anomalous == b.is_anomalous
            assert a.residual_zscore == b.residual_zscore
            assert a.low_data_quality == b.low_data_quality


class TestSTLPipelineRepoIntegration:
    """Verify the CalendarRepository path works end-to-end."""

    def test_analyse_with_repo_returns_same_results(self) -> None:
        cfg = STLDetectionConfig()
        readings, calendar = _build_full_window()

        # Direct path (calendar list)
        service_direct = STLDetectionService(config=cfg)
        direct_results = service_direct.analyse_circuit_window(readings, calendar)

        # Repo path
        repo = InMemoryCalendarRepository(calendar)
        service_repo = STLDetectionService(config=cfg, calendar_repo=repo)
        repo_results = service_repo.analyse_circuit_window_with_repo(readings, BUILDING_ID)

        assert len(direct_results) == len(repo_results)
        for a, b in zip(direct_results, repo_results):
            assert a.ts == b.ts
            assert a.is_anomalous == b.is_anomalous
            assert a.residual_zscore == b.residual_zscore
