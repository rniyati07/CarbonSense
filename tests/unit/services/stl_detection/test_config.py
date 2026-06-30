"""ENG-3c unit tests — STLDetectionConfig.

Verifies that all documented threshold constants are present, correctly
typed, and match their documented default values.  Any change to a default
must be conscious and cause this test to fail as a review gate.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from services.stl_detection.config import STLDetectionConfig


@pytest.mark.unit
class TestSTLDetectionConfigDefaults:
    """Verify every constant matches its documented implementation default."""

    def test_stl_period_hours_default(self) -> None:
        cfg = STLDetectionConfig()
        assert cfg.stl_period_hours == 24, (
            "STL period should be 24 for hourly COMBED data (one daily cycle)"
        )

    def test_residual_zscore_anomaly_threshold_default(self) -> None:
        cfg = STLDetectionConfig()
        assert cfg.residual_zscore_anomaly_threshold == 3.0, (
            "Implementation default is 3-sigma; changing this needs empirical "
            "justification against the COMBED fixture"
        )

    def test_stl_min_history_observations_default(self) -> None:
        cfg = STLDetectionConfig()
        assert cfg.stl_min_history_observations == 48, (
            "Minimum 48 observations = 2 complete daily cycles (2 × 24h)"
        )

    def test_stl_robust_default(self) -> None:
        cfg = STLDetectionConfig()
        assert cfg.stl_robust is True, "Robust fitting should be on by default"

    def test_stl_seasonal_deg_default(self) -> None:
        cfg = STLDetectionConfig()
        assert cfg.stl_seasonal_deg == 1

    def test_stl_trend_deg_default(self) -> None:
        cfg = STLDetectionConfig()
        assert cfg.stl_trend_deg == 1

    def test_stl_smoothing_windows_default_none(self) -> None:
        cfg = STLDetectionConfig()
        assert cfg.stl_seasonal_smoothing_window is None
        assert cfg.stl_trend_smoothing_window is None


@pytest.mark.unit
class TestSTLDetectionConfigTypes:
    """Verify fields have the expected Python types."""

    def test_period_is_int(self) -> None:
        assert isinstance(STLDetectionConfig().stl_period_hours, int)

    def test_threshold_is_float(self) -> None:
        assert isinstance(STLDetectionConfig().residual_zscore_anomaly_threshold, float)

    def test_min_history_is_int(self) -> None:
        assert isinstance(STLDetectionConfig().stl_min_history_observations, int)

    def test_robust_is_bool(self) -> None:
        assert isinstance(STLDetectionConfig().stl_robust, bool)


@pytest.mark.unit
class TestSTLDetectionConfigValidation:
    """Verify Pydantic validation rejects nonsensical values."""

    def test_rejects_zero_period(self) -> None:
        with pytest.raises(ValidationError):
            STLDetectionConfig(stl_period_hours=0)

    def test_rejects_negative_threshold(self) -> None:
        with pytest.raises(ValidationError):
            STLDetectionConfig(residual_zscore_anomaly_threshold=-1.0)

    def test_rejects_zero_threshold(self) -> None:
        with pytest.raises(ValidationError):
            STLDetectionConfig(residual_zscore_anomaly_threshold=0.0)

    def test_rejects_min_history_less_than_2(self) -> None:
        with pytest.raises(ValidationError):
            STLDetectionConfig(stl_min_history_observations=1)

    def test_allows_custom_threshold(self) -> None:
        cfg = STLDetectionConfig(residual_zscore_anomaly_threshold=2.5)
        assert cfg.residual_zscore_anomaly_threshold == 2.5
