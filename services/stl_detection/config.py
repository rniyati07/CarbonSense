"""ENG-3c — STL Residual Detection configuration.

All thresholds and tuning constants are centralised here as named typed
fields on STLDetectionConfig.  Service code and test code MUST import
constants from this module — never hardcode a numeric threshold elsewhere.

Implementation defaults and their rationale
-------------------------------------------
STL_PERIOD_HOURS (24)
    COMBED data is resampled to hourly granularity (TRD §3.1 / ENG-3a-1).
    A 24-hour period captures the dominant intra-day consumption cycle.

RESIDUAL_ZSCORE_ANOMALY_THRESHOLD (3.0)
    TRD §3.3 specifies that anomalies are flagged where |z| > threshold but
    does NOT specify the numeric value.  3.0 (three-sigma) is the industry
    default for this class of detector.
    *** IMPLEMENTATION DEFAULT — empirically calibrate against the COMBED
    golden fixture once ENG-3a's labelled export is available (ENG-6c). ***

STL_MIN_HISTORY_OBSERVATIONS (48)
    TRD §2.4 requires a minimum history window calibrated per building type
    but gives no global number.  48 = 2 × STL_PERIOD_HOURS: two complete
    daily cycles are the minimum for STL to separate seasonal from trend.
    *** IMPLEMENTATION DEFAULT — refine per building-type cluster once
    ENG-1d's building_calendar and ENG-3d's cold-start exit logic mature. ***

STL_ROBUST (True)
    Enables LOESS robust fitting, which downweights the influence of large
    residuals on the trend/seasonal fit.  This prevents a single anomalous
    day from corrupting the decomposed baseline — directly relevant to the
    detection use-case.

STL_SEASONAL_DEG / STL_TREND_DEG (1)
    Degree of the LOESS polynomial smoother for the seasonal and trend
    components respectively.  1 (linear) is the statsmodels default and
    sufficient for smooth building-consumption curves.

STL_SEASONAL_SMOOTHING_WINDOW (None → library default)
    statsmodels derives an appropriate odd window from the period when None.
    Override only if empirical tuning on COMBED reveals a better value.

STL_TREND_SMOOTHING_WINDOW (None → library default)
    Same rationale as the seasonal window.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class STLDetectionConfig(BaseModel):
    """Configuration for the STL Residual Detection service.

    All numeric thresholds MUST be sourced from this model.
    """

    # ------------------------------------------------------------------ #
    # Decomposition parameters
    # ------------------------------------------------------------------ #

    stl_period_hours: int = Field(
        default=24,
        ge=2,
        description=(
            "Seasonal period for STL decomposition (number of hourly observations "
            "per cycle).  24 = daily cycle for hourly COMBED data."
        ),
    )

    stl_robust: bool = Field(
        default=True,
        description=(
            "Use robust LOESS fitting to downweight outlier influence on the "
            "trend/seasonal components."
        ),
    )

    stl_seasonal_deg: int = Field(
        default=1,
        ge=0,
        le=1,
        description="Degree of the LOESS polynomial for the seasonal smoother (0 or 1).",
    )

    stl_trend_deg: int = Field(
        default=1,
        ge=0,
        le=1,
        description="Degree of the LOESS polynomial for the trend smoother (0 or 1).",
    )

    stl_seasonal_smoothing_window: int | None = Field(
        default=None,
        description=(
            "LOESS window size for the seasonal smoother.  None lets statsmodels "
            "compute an appropriate odd window from the period."
        ),
    )

    stl_trend_smoothing_window: int | None = Field(
        default=None,
        description=(
            "LOESS window size for the trend smoother.  None lets statsmodels "
            "compute an appropriate odd window from the period."
        ),
    )

    # ------------------------------------------------------------------ #
    # Anomaly flagging
    # ------------------------------------------------------------------ #

    residual_zscore_anomaly_threshold: float = Field(
        default=3.0,
        gt=0.0,
        description=(
            "Residual z-score magnitude above which a reading is flagged as "
            "anomalous (|z| > threshold).  "
            "IMPLEMENTATION DEFAULT (TRD §3.3 does not specify a value) — "
            "calibrate empirically against the COMBED golden fixture via ENG-6c."
        ),
    )

    # ------------------------------------------------------------------ #
    # Cold-start / data-quality
    # ------------------------------------------------------------------ #

    stl_min_history_observations: int = Field(
        default=48,
        ge=2,
        description=(
            "Minimum number of readings required per day-type cohort for STL "
            "to produce stable residuals.  Below this threshold the service "
            "emits low_data_quality=True instead of residual scores.  "
            "IMPLEMENTATION DEFAULT (TRD §2.4 defers the number to per-building "
            "calibration) — 48 = 2 × stl_period_hours (two full daily cycles)."
        ),
    )
