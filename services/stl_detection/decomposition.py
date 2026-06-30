"""ENG-3c — STL decomposition core (pure, stateless, deterministic).

All functions in this module are pure: no I/O, no side effects, no
randomness.  Given identical inputs they always produce identical outputs.
STL models are NEVER persisted — every call re-fits from scratch on the
provided series.

Key design decisions
--------------------
1.  Calendar-awareness lives in service.py, not here.
    decomposition.py receives an already-segmented pandas Series (one
    day-type cohort).  It knows nothing about CalendarEntry or DayType.
    This separation keeps the math layer testable in isolation.

2.  STL is re-fit per analysis window, not cached.
    Per TRD §3.3 and DATA_AND_MODEL_STRATEGY §5.3: "Re-fit per analysis
    window, not a persisted trained artifact."  There is no model state to
    save, load, or register.

3.  No MLflow, no sklearn, no Isolation Forest dependency.
    The only ML-adjacent library imported is statsmodels (a statistics
    library, not an ML framework) and numpy/pandas.

4.  Z-score computation uses robust statistics (median / MAD) instead of
    mean / std.  This prevents a large anomalous residual from inflating
    the standard deviation and masking subsequent anomalies — a known
    failure mode of naive z-scoring on anomaly detection residuals.
    The threshold constant in STLDetectionConfig still applies to these
    robust z-scores.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from statsmodels.tsa.seasonal import STL

from services.stl_detection.config import STLDetectionConfig
from services.stl_detection.exceptions import InsufficientHistoryError


@dataclass(frozen=True)
class STLDecompositionResult:
    """Output of fit_stl: the three additive components for a cohort series.

    All arrays have the same length as the input series and are aligned
    to its index.  Values are float64; no NaN entries are present (STL
    fills any internal NaN via its own smoothing).
    """

    trend: np.ndarray[Any, np.dtype[np.float64]]
    seasonal: np.ndarray[Any, np.dtype[np.float64]]
    residual: np.ndarray[Any, np.dtype[np.float64]]
    index: pd.DatetimeIndex  # original timestamps, for alignment


def check_cold_start(
    n_observations: int,
    config: STLDetectionConfig,
) -> tuple[bool, str | None]:
    """Determine whether a day-type cohort has enough history for stable STL.

    Parameters
    ----------
    n_observations:
        Number of readings available for this cohort.
    config:
        Service configuration carrying STL_MIN_HISTORY_OBSERVATIONS.

    Returns
    -------
    (is_low_quality, reason)
        is_low_quality=True when observations < stl_min_history_observations.
        reason is a human-readable explanation, or None when data is sufficient.
    """
    if n_observations < config.stl_min_history_observations:
        reason = (
            f"Insufficient observations for stable STL decomposition: "
            f"{n_observations} available, "
            f"minimum required is {config.stl_min_history_observations} "
            f"({config.stl_min_history_observations // config.stl_period_hours} "
            f"complete {config.stl_period_hours}-hour cycles). "
            "Cold-start condition — emitting low_data_quality indicator."
        )
        return True, reason
    return False, None


def fit_stl(
    series: pd.Series,
    config: STLDetectionConfig,
) -> STLDecompositionResult:
    """Fit STL decomposition on a single day-type cohort series.

    Parameters
    ----------
    series:
        Pandas Series of kWh readings indexed by UTC datetime, sorted
        ascending.  Must represent a single day-type cohort (e.g., all
        business-day readings in the analysis window).
        Length must be >= config.stl_min_history_observations; callers
        are responsible for calling check_cold_start first.
    config:
        Service configuration.

    Returns
    -------
    STLDecompositionResult
        Trend, seasonal, and residual component arrays aligned to series.index.

    Raises
    ------
    InsufficientHistoryError
        When len(series) < stl_min_history_observations.  The caller
        (STLDetectionService) catches this and converts it to a
        low_data_quality indicator.
    ValueError
        When series is empty or contains only NaN values.
    """
    n = len(series)
    if n < config.stl_min_history_observations:
        # Determine day_type label for the error message from the index if
        # possible; fall back to "<unknown>" since decomposition.py is
        # calendar-agnostic.
        raise InsufficientHistoryError(
            day_type="<unknown>",
            n_observations=n,
            minimum_required=config.stl_min_history_observations,
        )

    if series.isna().all():
        raise ValueError("series contains only NaN values — cannot fit STL.")

    # Forward-fill then backfill to handle sparse NaN from data-quality
    # degraded readings.  This preserves the series length (no drop).
    clean_series = series.ffill().bfill()

    # Build STL kwargs, omitting None window overrides so statsmodels
    # computes its own defaults from the period.
    stl_kwargs: dict[str, object] = {
        "period": config.stl_period_hours,
        "robust": config.stl_robust,
        "seasonal_deg": config.stl_seasonal_deg,
        "trend_deg": config.stl_trend_deg,
    }
    if config.stl_seasonal_smoothing_window is not None:
        stl_kwargs["seasonal"] = config.stl_seasonal_smoothing_window
    else:
        # Default to a robust seasonal smoothing window of 35 if not specified.
        # This prevents statsmodels default of 7 from absorbing short-term spikes.
        # We ensure it is not larger than the series length, keeping it odd and >= 7.
        s_win = 35
        n_obs = len(clean_series)
        if s_win > n_obs:
            s_win = n_obs if n_obs % 2 != 0 else n_obs - 1
            if s_win < 7:
                s_win = 7
        stl_kwargs["seasonal"] = s_win

    if config.stl_trend_smoothing_window is not None:
        stl_kwargs["trend"] = config.stl_trend_smoothing_window

    stl = STL(clean_series, **stl_kwargs)
    result = stl.fit()

    return STLDecompositionResult(
        trend=result.trend.to_numpy(),
        seasonal=result.seasonal.to_numpy(),
        residual=result.resid.to_numpy(),
        index=pd.DatetimeIndex(series.index),
    )


def compute_residual_zscores(
    residuals: np.ndarray[Any, np.dtype[np.float64]],
) -> np.ndarray[Any, np.dtype[np.float64]]:
    """Compute robust z-scores for an array of STL residuals.

    Uses the median absolute deviation (MAD) estimator instead of
    mean/std to avoid inflating the scale estimate when the residual
    array itself contains anomalous values.

    z_i = (r_i - median(r)) / (1.4826 * MAD(r))

    The 1.4826 factor makes the MAD-based scale consistent with the
    standard deviation under a normal distribution.

    When MAD = 0 (all residuals identical, e.g. flat series), returns
    an array of zeros — a flat series has no anomalous residual.

    Parameters
    ----------
    residuals:
        1-D numpy array of STL residual values from fit_stl().

    Returns
    -------
    np.ndarray
        Z-scores aligned index-for-index with the input array.
    """
    if residuals.size == 0:
        return np.array([], dtype=np.float64)

    median = np.median(residuals)
    mad = np.median(np.abs(residuals - median))

    if mad == 0.0:
        # Fall back to Mean Absolute Deviation if Median Absolute Deviation is zero
        # (e.g. when >50% of residuals are identical, but outliers still exist)
        mad = np.mean(np.abs(residuals - median))

    if mad == 0.0:
        return np.zeros_like(residuals, dtype=np.float64)

    # 1.4826 is the standard consistency factor for the normal distribution
    scale = 1.4826 * mad
    if scale < 1e-6:
        # Scale floor prevents floating-point noise amplification in flat series
        scale = 1e-6
    return np.asarray((residuals - median) / scale, dtype=np.float64)


def flag_anomalies(
    zscores: np.ndarray[Any, np.dtype[np.float64]],
    config: STLDetectionConfig,
) -> np.ndarray[Any, np.dtype[np.bool_]]:
    """Return a boolean mask where |zscore| > anomaly threshold.

    Parameters
    ----------
    zscores:
        Array of robust z-scores from compute_residual_zscores().
    config:
        Service configuration carrying residual_zscore_anomaly_threshold.

    Returns
    -------
    np.ndarray[bool]
        True at positions where the reading is anomalous.
    """
    return np.asarray(np.abs(zscores) > config.residual_zscore_anomaly_threshold, dtype=np.bool_)
