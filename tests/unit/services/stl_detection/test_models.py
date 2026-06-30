"""ENG-3c unit tests — Pydantic models.

Tests the data model invariants, especially the validator that ensures
low_data_quality=True is never paired with populated residual scores.
"""

from __future__ import annotations

import datetime
import uuid

import pytest
from pydantic import ValidationError

from services.stl_detection.models import (
    CalendarEntry,
    DayType,
    STLResidualResult,
    STLWindowResult,
)

TENANT_ID = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
CIRCUIT_ID = uuid.UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")
BUILDING_ID = uuid.UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")

NOW = datetime.datetime(2026, 1, 5, 9, 0, 0, tzinfo=datetime.UTC)


@pytest.mark.unit
class TestDayType:
    def test_all_four_values_exist(self) -> None:
        assert DayType.BUSINESS_DAY == "business_day"
        assert DayType.WEEKEND == "weekend"
        assert DayType.HOLIDAY == "holiday"
        assert DayType.DECLARED_CLOSURE == "declared_closure"

    def test_invalid_day_type_raises(self) -> None:
        with pytest.raises(ValidationError):
            CalendarEntry(
                building_id=BUILDING_ID,
                date=datetime.date(2026, 1, 5),
                day_type="unknown_day",  # type: ignore[arg-type]
            )


@pytest.mark.unit
class TestCalendarEntry:
    def test_valid_entry(self) -> None:
        entry = CalendarEntry(
            building_id=BUILDING_ID,
            date=datetime.date(2026, 1, 5),
            day_type=DayType.BUSINESS_DAY,
        )
        assert entry.day_type == DayType.BUSINESS_DAY
        assert entry.building_id == BUILDING_ID

    def test_all_day_types_accepted(self) -> None:
        for dt in DayType:
            entry = CalendarEntry(
                building_id=BUILDING_ID,
                date=datetime.date(2026, 1, 5),
                day_type=dt,
            )
            assert entry.day_type == dt


@pytest.mark.unit
class TestSTLResidualResult:
    def _make_valid_result(self, **overrides: object) -> STLResidualResult:
        defaults: dict[str, object] = {
            "tenant_id": TENANT_ID,
            "circuit_id": CIRCUIT_ID,
            "ts": NOW,
            "kwh": 12.5,
            "day_type": DayType.BUSINESS_DAY,
            "stl_trend": 10.0,
            "stl_seasonal": 1.5,
            "stl_residual": 1.0,
            "residual_zscore": 0.5,
            "residual_magnitude": 1.0,
            "is_anomalous": False,
            "low_data_quality": False,
        }
        defaults.update(overrides)
        return STLResidualResult(**defaults)  # type: ignore[arg-type]

    def test_normal_result_accepted(self) -> None:
        result = self._make_valid_result()
        assert result.is_anomalous is False
        assert result.low_data_quality is False

    def test_anomalous_result_accepted(self) -> None:
        result = self._make_valid_result(is_anomalous=True, residual_zscore=4.5)
        assert result.is_anomalous is True

    def test_low_data_quality_with_none_scores_accepted(self) -> None:
        result = STLResidualResult(
            tenant_id=TENANT_ID,
            circuit_id=CIRCUIT_ID,
            ts=NOW,
            day_type=DayType.HOLIDAY,
            low_data_quality=True,
            low_data_quality_reason="Insufficient history: 10 < 48 required.",
        )
        assert result.low_data_quality is True
        assert result.residual_zscore is None
        assert result.residual_magnitude is None

    def test_low_data_quality_with_zscore_raises(self) -> None:
        """low_data_quality=True + residual_zscore is set → validation error."""
        with pytest.raises(ValidationError):
            STLResidualResult(
                tenant_id=TENANT_ID,
                circuit_id=CIRCUIT_ID,
                ts=NOW,
                day_type=DayType.HOLIDAY,
                low_data_quality=True,
                residual_zscore=1.0,  # must be None when low_data_quality
                low_data_quality_reason="some reason",
            )

    def test_low_data_quality_without_reason_raises(self) -> None:
        """low_data_quality=True with no reason → validation error."""
        with pytest.raises(ValidationError):
            STLResidualResult(
                tenant_id=TENANT_ID,
                circuit_id=CIRCUIT_ID,
                ts=NOW,
                day_type=DayType.BUSINESS_DAY,
                low_data_quality=True,
                low_data_quality_reason=None,  # required when flag is True
            )

    def test_fields_serialise_to_dict(self) -> None:
        result = self._make_valid_result()
        d = result.model_dump()
        assert "stl_residual" in d
        assert "residual_zscore" in d
        assert "residual_magnitude" in d
        assert "day_type" in d
        assert "low_data_quality" in d


@pytest.mark.unit
class TestSTLWindowResult:
    def test_summary_counts_computed_automatically(self) -> None:
        readings = [
            STLResidualResult(
                tenant_id=TENANT_ID,
                circuit_id=CIRCUIT_ID,
                ts=NOW + datetime.timedelta(hours=i),
                day_type=DayType.BUSINESS_DAY,
                is_anomalous=(i == 5),
                low_data_quality=False,
            )
            for i in range(10)
        ]
        window = STLWindowResult(
            tenant_id=TENANT_ID,
            building_id=BUILDING_ID,
            circuit_id=CIRCUIT_ID,
            window_start=NOW,
            window_end=NOW + datetime.timedelta(hours=9),
            readings=readings,
        )
        assert window.total_readings == 10
        assert window.anomalous_count == 1
        assert window.low_data_quality_count == 0

    def test_empty_readings_counts_are_zero(self) -> None:
        window = STLWindowResult(
            tenant_id=TENANT_ID,
            building_id=BUILDING_ID,
            circuit_id=CIRCUIT_ID,
            window_start=NOW,
            window_end=NOW,
            readings=[],
        )
        assert window.total_readings == 0
        assert window.anomalous_count == 0
