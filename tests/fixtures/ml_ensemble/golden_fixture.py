"""ENG-3d — Golden fixture generator for ML Ensemble tests.

Produces three distinct anomaly classes so that ENG-3d tests can prove that
Isolation Forest and the Windowed Autoencoder have LOW BLIND-SPOT OVERLAP:

    Normal series:
        30 days × 24 h of sinusoidal hourly kWh with low-amplitude Gaussian noise
        (std=0.3 kWh ≈ 3% of mean).  Noise is required so sklearn's IsolationForest
        can distinguish in-distribution from out-of-distribution points (zero-noise
        data collapses to discrete feature clusters with no isolation gradient).
        Both IF and AE should treat these as normal.

    Global outlier anomaly (IF target):
        A few isolated readings with kWh >> 10× normal peak.
        These are point anomalies: a single hour with extreme magnitude.
        Isolation Forest is designed to catch these; AE may or may not.

    Shape / pattern anomaly (AE target):
        A full 24-hour period with FLAT (constant) consumption at the baseline mean.
        Each individual reading has normal feature values (efficiency=1.0, residual=0)
        so Isolation Forest should NOT flag it.  The temporal pattern differs from
        the sinusoidal training distribution, so the Autoencoder produces high
        reconstruction error for this window.

Usage
-----
::

    from tests.fixtures.ml_ensemble.golden_fixture import (
        make_normal_features,
        make_global_outlier_features,
        make_shape_anomaly_features,
        TENANT_ID, BUILDING_ID, CIRCUIT_ID,
    )
"""

from __future__ import annotations

import datetime
import math
from uuid import UUID

from models.feature_store.feature_set_v1 import FeatureSetV1

# ------------------------------------------------------------------ #
# Canonical IDs
# ------------------------------------------------------------------ #

TENANT_ID: UUID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
BUILDING_ID: UUID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
CIRCUIT_ID: UUID = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")

# Normal sinusoidal profile parameters
_BASE_KWH: float = 10.0
_AMPLITUDE: float = 4.0  # peak is 14 kWh, floor is 6 kWh

# Start date for the normal series (Monday)
_START_DATE = datetime.date(2026, 1, 5)


def _make_feature(
    ts: datetime.datetime,
    kwh: float,
    rule_fire_indicators: dict[str, bool] | None = None,
    low_data_quality: bool = False,
    stl_residual_magnitude: float | None = None,
    day_type: str = "business_day",
) -> FeatureSetV1:
    """Helper: construct a FeatureSetV1 with realistic rolling stats derived from kwh.

    rolling_baseline_kwh is set to the 7-day mean of a typical sinusoidal day
    (midpoint of [6, 14] range = 10.0) so that rolling_efficiency_ratio = kwh/10.0
    varies meaningfully with kwh.  This ensures IF can usefully split on this feature.
    """
    rolling_baseline = 10.0  # fixed 7-day mean so efficiency ratio varies with kwh
    efficiency = kwh / rolling_baseline if rolling_baseline > 0 else 1.0
    # Derive stl_residual_magnitude from kwh deviation when not explicitly supplied.
    # This ensures non-zero variance across the training corpus so IF can split on it.
    if stl_residual_magnitude is None:
        stl_residual_magnitude = abs(kwh - rolling_baseline)
    return FeatureSetV1(
        tenant_id=TENANT_ID,
        circuit_id=CIRCUIT_ID,
        ts=ts,
        rolling_baseline_kwh=rolling_baseline,
        peak_offpeak_split=1.0 if 9 <= ts.hour <= 20 else 0.0,
        after_hours_kwh_ratio=0.0 if 8 <= ts.hour < 18 else 1.0,
        weekend_floor_load=None,
        rolling_efficiency_ratio=efficiency,
        stl_residual_magnitude=stl_residual_magnitude,
        day_type=day_type,
        rule_fire_indicators=rule_fire_indicators or {},
        low_data_quality=low_data_quality,
    )


def make_normal_features(n_days: int = 30, seed: int = 0) -> list[FeatureSetV1]:
    """Generate n_days × 24 h of sinusoidal normal-operation features with Gaussian noise.

    The base profile is sinusoidal (peaks at midday, troughs at midnight).
    Low-amplitude Gaussian noise is added to each reading so the training
    distribution is continuous rather than a discrete set of repeated points.
    Without noise, sklearn's IsolationForest cannot isolate anomalies because
    all "normal" training points occupy a small set of identical feature vectors.

    Parameters
    ----------
    n_days:
        Number of days.  Default 30 (720 rows) gives enough windows for AE
        training with default window_length_hours=24.
    seed:
        Random seed for noise generation.  Default 0 for reproducibility.
    """
    rng = __import__("numpy").random.default_rng(seed)
    features: list[FeatureSetV1] = []
    for day in range(n_days):
        current_date = _START_DATE + datetime.timedelta(days=day)
        day_type = "weekend" if current_date.isoweekday() in (6, 7) else "business_day"
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
            # Sinusoidal base + small noise (std=0.3 kWh ≈ 3% of mean)
            base_kwh = _BASE_KWH + _AMPLITUDE * math.sin(math.pi * hour / 23.0)
            kwh = max(0.1, base_kwh + float(rng.normal(0, 0.3)))
            features.append(
                _make_feature(
                    ts=ts,
                    kwh=kwh,
                    day_type=day_type,
                )
            )
    return features


def make_global_outlier_features(
    n_outliers: int = 5,
    outlier_multiplier: float = 15.0,
    start_offset_days: int = 5,
) -> list[FeatureSetV1]:
    """Generate point-anomaly features: isolated hours with extreme kWh magnitude.

    These represent the anomaly class that Isolation Forest is designed to catch.
    Each outlier is a SINGLE isolated reading — not part of a sustained pattern.
    The outlier magnitude is outlier_multiplier × normal peak.

    Parameters
    ----------
    n_outliers:
        Number of isolated extreme readings to generate.
    outlier_multiplier:
        Factor by which the outlier exceeds normal peak kWh.
    start_offset_days:
        Day offset from _START_DATE where outliers are placed.
    """
    features: list[FeatureSetV1] = []
    for i in range(n_outliers):
        day_offset = start_offset_days + i * 3
        current_date = _START_DATE + datetime.timedelta(days=day_offset)
        ts = datetime.datetime(
            current_date.year,
            current_date.month,
            current_date.day,
            14,  # mid-afternoon
            0,
            0,
            tzinfo=datetime.UTC,
        )
        kwh = (_BASE_KWH + _AMPLITUDE) * outlier_multiplier  # 14 * 15 = 210 kWh
        rolling_baseline = 10.0  # same fixed baseline as _make_feature
        features.append(
            FeatureSetV1(
                tenant_id=TENANT_ID,
                circuit_id=CIRCUIT_ID,
                ts=ts,
                rolling_baseline_kwh=rolling_baseline,
                peak_offpeak_split=1.0,
                after_hours_kwh_ratio=0.0,
                weekend_floor_load=None,
                rolling_efficiency_ratio=kwh / rolling_baseline,  # 210/10 = 21.0
                stl_residual_magnitude=kwh - rolling_baseline,    # 210-10 = 200.0
                day_type="business_day",
                rule_fire_indicators={},
                low_data_quality=False,
            )
        )
    return features


def make_shape_anomaly_features(
    n_days: int = 2,
    start_offset_days: int = 20,
) -> list[FeatureSetV1]:
    """Generate shape/pattern anomaly features: FLAT (constant) consumption profile.

    These represent the anomaly class the Autoencoder is designed to catch.

    Design choice: flat consumption at the baseline mean value (_BASE_KWH = 10.0).
    This gives per-reading feature values that are perfectly NORMAL for IF:
        rolling_efficiency_ratio = 10.0 / 10.0 = 1.0  (within [0.6, 1.4])
        stl_residual_magnitude   = |10.0 - 10.0| = 0   (within [0, 4])

    The temporal PATTERN is anomalous: a flat line instead of a sinusoidal curve.
    The Autoencoder, trained on sinusoidal patterns, reconstructs sinusoids poorly
    when presented with flat windows → high per-window reconstruction error.

    The inverted-sinusoid design was NOT used because an inverted pattern creates
    unusual feature COMBINATIONS (high efficiency at off-peak times) that
    Isolation Forest can partially detect, violating the blind-spot separation goal.

    Isolation Forest should NOT flag these (each individual reading is at the mean).
    The Autoencoder should flag these (temporal pattern differs from training).

    Parameters
    ----------
    n_days:
        Number of consecutive days with flat profiles.
    start_offset_days:
        Day offset from _START_DATE for placing the anomalous window.
    """
    features: list[FeatureSetV1] = []
    for day in range(n_days):
        day_offset = start_offset_days + day
        current_date = _START_DATE + datetime.timedelta(days=day_offset)
        day_type = "weekend" if current_date.isoweekday() in (6, 7) else "business_day"
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
            # Flat at the baseline mean: each individual reading looks normal to IF
            kwh = _BASE_KWH  # 10.0 — exactly at the rolling mean
            features.append(
                _make_feature(
                    ts=ts,
                    kwh=kwh,
                    day_type=day_type,
                )
            )
    return features


def make_training_corpus(n_normal_days: int = 30) -> list[FeatureSetV1]:
    """Return a clean training corpus: normal data only (no anomalies).

    This is what the trainers should be trained on — normal operation.
    Anomalies are injected separately at inference time to measure detection.
    """
    return make_normal_features(n_days=n_normal_days)
