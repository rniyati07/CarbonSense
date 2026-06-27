"""ENG-3c unit tests — Feature output (ENG-3c-2).

Verifies that FeatureSetV1STLFields can be constructed from every
STLResidualResult and that all four ENG-3c-2 output fields are present
and correctly typed.

These tests guard the ENG-3c → ENG-3d-1 integration contract.
"""

from __future__ import annotations

import datetime
import uuid

import pytest

from models.feature_store.feature_set_v1 import FeatureSetV1STLFields
from services.stl_detection.config import STLDetectionConfig
from services.stl_detection.models import DayType, STLResidualResult
from services.stl_detection.service import STLDetectionService
from tests.unit.services.stl_detection.conftest import (
    CIRCUIT_ID,
    TENANT_ID,
    build_sufficient_business_day_series,
)

NOW = datetime.datetime(2026, 1, 5, 9, 0, 0, tzinfo=datetime.timezone.utc)


def _make_result(
    *,
    stl_residual: float | None = 1.0,
    residual_zscore: float | None = 0.5,
    residual_magnitude: float | None = 1.0,
    day_type: DayType = DayType.BUSINESS_DAY,
    low_data_quality: bool = False,
    low_data_quality_reason: str | None = None,
) -> STLResidualResult:
    return STLResidualResult(
        tenant_id=TENANT_ID,
        circuit_id=CIRCUIT_ID,
        ts=NOW,
        day_type=day_type,
        stl_residual=stl_residual,
        residual_zscore=residual_zscore,
        residual_magnitude=residual_magnitude,
        is_anomalous=False,
        low_data_quality=low_data_quality,
        low_data_quality_reason=low_data_quality_reason,
    )


@pytest.mark.unit
class TestFeatureSetV1STLFields:
    def test_all_four_feature_fields_present(self) -> None:
        result = _make_result()
        feature = FeatureSetV1STLFields.from_stl_result(result)

        # ENG-3c-2 mandated fields
        assert hasattr(feature, "stl_residual")
        assert hasattr(feature, "residual_zscore")
        assert hasattr(feature, "residual_magnitude")
        assert hasattr(feature, "day_type")
        assert hasattr(feature, "low_data_quality")

    def test_field_values_match_result(self) -> None:
        result = _make_result(
            stl_residual=2.3,
            residual_zscore=1.8,
            residual_magnitude=2.3,
            day_type=DayType.HOLIDAY,
        )
        feature = FeatureSetV1STLFields.from_stl_result(result)

        assert feature.stl_residual == pytest.approx(2.3)
        assert feature.residual_zscore == pytest.approx(1.8)
        assert feature.residual_magnitude == pytest.approx(2.3)
        assert feature.day_type == "holiday"
        assert feature.low_data_quality is False

    def test_day_type_is_one_of_four_valid_values(self) -> None:
        valid_values = {"business_day", "weekend", "holiday", "declared_closure"}
        for dt in DayType:
            result = _make_result(day_type=dt)
            feature = FeatureSetV1STLFields.from_stl_result(result)
            assert feature.day_type in valid_values

    def test_low_data_quality_propagated(self) -> None:
        result = STLResidualResult(
            tenant_id=TENANT_ID,
            circuit_id=CIRCUIT_ID,
            ts=NOW,
            day_type=DayType.HOLIDAY,
            low_data_quality=True,
            low_data_quality_reason="Insufficient history: 10 < 48 required.",
        )
        feature = FeatureSetV1STLFields.from_stl_result(result)
        assert feature.low_data_quality is True
        assert feature.stl_residual is None
        assert feature.residual_zscore is None
        assert feature.residual_magnitude is None

    def test_feature_from_every_result_in_window(self) -> None:
        """FeatureSetV1STLFields must be constructable from every STL result."""
        cfg = STLDetectionConfig()
        service = STLDetectionService(config=cfg)
        readings, calendar = build_sufficient_business_day_series(cfg)

        results = service.analyse_circuit_window(readings, calendar)

        for stl_result in results:
            feature = FeatureSetV1STLFields.from_stl_result(stl_result)
            # No exception → contract satisfied
            assert feature.day_type in {
                "business_day", "weekend", "holiday", "declared_closure"
            }

    def test_feature_fields_correct_types(self) -> None:
        result = _make_result()
        feature = FeatureSetV1STLFields.from_stl_result(result)

        assert isinstance(feature.stl_residual, (float, type(None)))
        assert isinstance(feature.residual_zscore, (float, type(None)))
        assert isinstance(feature.residual_magnitude, (float, type(None)))
        assert isinstance(feature.day_type, str)
        assert isinstance(feature.low_data_quality, bool)

    def test_feature_serialises_to_dict(self) -> None:
        result = _make_result()
        feature = FeatureSetV1STLFields.from_stl_result(result)
        d = feature.model_dump()

        assert set(d.keys()) >= {
            "stl_residual", "residual_zscore", "residual_magnitude",
            "day_type", "low_data_quality",
        }

    def test_feature_from_stl_result_cold_start_no_crash(self) -> None:
        """from_stl_result must not raise when fields are None (cold-start)."""
        cold_result = STLResidualResult(
            tenant_id=TENANT_ID,
            circuit_id=CIRCUIT_ID,
            ts=NOW,
            day_type=DayType.BUSINESS_DAY,
            low_data_quality=True,
            low_data_quality_reason="Test cold-start reason.",
        )
        feature = FeatureSetV1STLFields.from_stl_result(cold_result)
        assert feature.low_data_quality is True
        assert feature.stl_residual is None
