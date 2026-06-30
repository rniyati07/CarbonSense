"""ENG-3c unit tests — decomposition.py (pure functions).

Tests are fully deterministic: no randomness, no I/O.
Input series are constructed analytically so expected residuals are known.
"""

from __future__ import annotations

import datetime
import math

import numpy as np
import pandas as pd
import pytest

from services.stl_detection.config import STLDetectionConfig
from services.stl_detection.decomposition import (
    check_cold_start,
    compute_residual_zscores,
    fit_stl,
    flag_anomalies,
)
from services.stl_detection.exceptions import InsufficientHistoryError


def _make_series(n_periods: int = 3, period: int = 24) -> pd.Series:
    """Synthetic sinusoidal series: trend=0, clear seasonal, residual≈0."""
    n = n_periods * period
    start = datetime.datetime(2026, 1, 5, 0, 0, 0, tzinfo=datetime.UTC)
    index = [start + datetime.timedelta(hours=h) for h in range(n)]
    values = [10.0 + 5.0 * math.sin(2 * math.pi * h / period) for h in range(n)]
    return pd.Series(values, index=pd.DatetimeIndex(index, tz=datetime.UTC))


# ------------------------------------------------------------------ #
# check_cold_start
# ------------------------------------------------------------------ #


@pytest.mark.unit
class TestCheckColdStart:
    def test_insufficient_history_returns_true(self) -> None:
        cfg = STLDetectionConfig()
        is_low, reason = check_cold_start(
            n_observations=cfg.stl_min_history_observations - 1, config=cfg
        )
        assert is_low is True
        assert reason is not None
        assert len(reason) > 0

    def test_exact_minimum_returns_false(self) -> None:
        cfg = STLDetectionConfig()
        is_low, reason = check_cold_start(
            n_observations=cfg.stl_min_history_observations, config=cfg
        )
        assert is_low is False
        assert reason is None

    def test_above_minimum_returns_false(self) -> None:
        cfg = STLDetectionConfig()
        is_low, reason = check_cold_start(
            n_observations=cfg.stl_min_history_observations + 100, config=cfg
        )
        assert is_low is False
        assert reason is None

    def test_zero_observations_is_low_quality(self) -> None:
        cfg = STLDetectionConfig()
        is_low, reason = check_cold_start(0, cfg)
        assert is_low is True

    def test_reason_mentions_observation_count(self) -> None:
        cfg = STLDetectionConfig()
        is_low, reason = check_cold_start(10, cfg)
        assert is_low is True
        assert "10" in (reason or "")


# ------------------------------------------------------------------ #
# fit_stl
# ------------------------------------------------------------------ #


@pytest.mark.unit
class TestFitSTL:
    def test_raises_insufficient_history_on_short_series(self) -> None:
        cfg = STLDetectionConfig()
        short_series = _make_series(n_periods=1, period=24)  # 24 < 48
        with pytest.raises(InsufficientHistoryError):
            fit_stl(short_series, cfg)

    def test_decomposes_sinusoidal_series(self) -> None:
        cfg = STLDetectionConfig()
        series = _make_series(n_periods=4, period=24)  # 96 >= 48
        result = fit_stl(series, cfg)
        assert result.trend is not None
        assert result.seasonal is not None
        assert result.residual is not None
        assert len(result.residual) == len(series)

    def test_residual_small_for_pure_seasonal_series(self) -> None:
        """For a perfect sinusoid, residuals should be near zero."""
        cfg = STLDetectionConfig()
        series = _make_series(n_periods=5, period=24)
        result = fit_stl(series, cfg)
        # Residual std should be much smaller than the seasonal amplitude (5.0)
        assert np.std(result.residual) < 1.5, (
            f"Expected small residuals for a clean sinusoidal series, "
            f"got std={np.std(result.residual):.4f}"
        )

    def test_output_arrays_same_length_as_input(self) -> None:
        cfg = STLDetectionConfig()
        series = _make_series(n_periods=4)
        result = fit_stl(series, cfg)
        n = len(series)
        assert len(result.trend) == n
        assert len(result.seasonal) == n
        assert len(result.residual) == n
        assert len(result.index) == n

    def test_deterministic_output(self) -> None:
        """Same input → same output every time."""
        cfg = STLDetectionConfig()
        series = _make_series(n_periods=4)
        result_a = fit_stl(series, cfg)
        result_b = fit_stl(series, cfg)
        np.testing.assert_array_equal(result_a.residual, result_b.residual)
        np.testing.assert_array_equal(result_a.trend, result_b.trend)
        np.testing.assert_array_equal(result_a.seasonal, result_b.seasonal)

    def test_raises_on_all_nan_series(self) -> None:
        cfg = STLDetectionConfig()
        n = cfg.stl_min_history_observations + 10
        start = datetime.datetime(2026, 1, 5, tzinfo=datetime.UTC)
        index = [start + datetime.timedelta(hours=h) for h in range(n)]
        series = pd.Series([float("nan")] * n, index=pd.DatetimeIndex(index))
        with pytest.raises(ValueError, match="only NaN"):
            fit_stl(series, cfg)

    def test_handles_sparse_nan(self) -> None:
        """Series with a few NaN values should not crash (ffill/bfill applied)."""
        cfg = STLDetectionConfig()
        series = _make_series(n_periods=4)
        # Inject NaN at position 10
        series_list = series.tolist()
        series_list[10] = float("nan")
        series_nan = pd.Series(series_list, index=series.index)
        result = fit_stl(series_nan, cfg)
        assert not np.any(np.isnan(result.residual))


# ------------------------------------------------------------------ #
# compute_residual_zscores
# ------------------------------------------------------------------ #


@pytest.mark.unit
class TestComputeResidualZscores:
    def test_zero_residuals_produce_zero_zscores(self) -> None:
        residuals = np.zeros(50)
        zscores = compute_residual_zscores(residuals)
        np.testing.assert_array_equal(zscores, np.zeros(50))

    def test_identical_residuals_produce_zero_zscores(self) -> None:
        residuals = np.full(50, 5.0)
        zscores = compute_residual_zscores(residuals)
        np.testing.assert_array_equal(zscores, np.zeros(50))

    def test_large_outlier_has_large_zscore(self) -> None:
        residuals = np.array([1.0] * 49 + [100.0])
        zscores = compute_residual_zscores(residuals)
        assert abs(zscores[-1]) > 10.0, "Outlier should have a very high z-score"

    def test_output_length_matches_input(self) -> None:
        residuals = np.random.default_rng(42).standard_normal(60)
        zscores = compute_residual_zscores(residuals)
        assert len(zscores) == 60

    def test_empty_array_returns_empty(self) -> None:
        result = compute_residual_zscores(np.array([]))
        assert len(result) == 0

    def test_median_residual_has_zero_zscore(self) -> None:
        """The median-valued residual should have z-score ≈ 0."""
        residuals = np.arange(51, dtype=float)  # symmetric, median=25
        zscores = compute_residual_zscores(residuals)
        assert abs(zscores[25]) < 0.01

    def test_deterministic(self) -> None:
        residuals = np.linspace(-5, 5, 100)
        z1 = compute_residual_zscores(residuals)
        z2 = compute_residual_zscores(residuals)
        np.testing.assert_array_equal(z1, z2)


# ------------------------------------------------------------------ #
# flag_anomalies
# ------------------------------------------------------------------ #


@pytest.mark.unit
class TestFlagAnomalies:
    def test_flags_values_above_threshold(self) -> None:
        cfg = STLDetectionConfig(residual_zscore_anomaly_threshold=3.0)
        zscores = np.array([0.5, 1.0, 2.9, 3.0, 3.1, 10.0, -3.5, -2.5])
        flags = flag_anomalies(zscores, cfg)
        # |z| > 3.0 → anomalous
        expected = np.array([False, False, False, False, True, True, True, False])
        np.testing.assert_array_equal(flags, expected)

    def test_custom_threshold_respected(self) -> None:
        cfg = STLDetectionConfig(residual_zscore_anomaly_threshold=2.0)
        zscores = np.array([1.9, 2.0, 2.1])
        flags = flag_anomalies(zscores, cfg)
        assert flags[0] is np.bool_(False)
        assert flags[1] is np.bool_(False)
        assert flags[2] is np.bool_(True)

    def test_empty_input(self) -> None:
        cfg = STLDetectionConfig()
        result = flag_anomalies(np.array([]), cfg)
        assert len(result) == 0
