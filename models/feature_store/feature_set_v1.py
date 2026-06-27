"""ENG-3c-2 — Feature schema seed for feature_set_v1.

Status: TEMPORARY SEED — finalised by ENG-3d-1
--------------------------------------------------------
ENG-3d-1 will assemble the complete feature_set_v1 by merging:
    - FeatureSetV1STLFields (this module, contributed by ENG-3c)
    - Rolling statistics (derived time-series features, ENG-3d-1)
    - Calendar features (day_type, occupancy schedule)
    - Rule-fire indicators (binary per rule_id, contributed by ENG-3b)

Do NOT create a divergent copy of this schema in any other service.
Import from models.feature_store.feature_set_v1 wherever feature_set_v1
fields are needed.

Why this file exists here (not in services/stl_detection/)
-----------------------------------------------------------
DATA_AND_MODEL_STRATEGY §3.7 specifies that feature_set_v1 lives under
models/feature_store/ and is defined once.  Multiple services (STL
detection, ML Ensemble, GNN research track) consume it.  Placing it in
a service module would invert the dependency direction.

Field documentation (ENG-3c-2 scope)
--------------------------------------
stl_residual
    The raw residual component from the STL decomposition:
    kwh_reading - trend - seasonal.  Positive = consumption above the
    decomposed baseline; negative = below.

residual_zscore
    Robust z-score of the residual using the MAD estimator.  The anomaly
    threshold (|z| > config.residual_zscore_anomaly_threshold) is applied
    by STLDetectionService; this field carries the raw score for downstream
    use (ML Ensemble input, SHAP features, Confidence Calibration context).

residual_magnitude
    abs(stl_residual).  A non-negative scalar encoding how far the reading
    deviates from the building's decomposed baseline regardless of direction.
    Used as a feature magnitude signal by the ML Ensemble.

day_type
    The building_calendar classification of the reading's date.
    One of: business_day | weekend | holiday | declared_closure.
    Downstream ML models use this as a categorical feature alongside the
    numeric residual signals.

low_data_quality
    True when the STL layer could not produce stable residuals due to
    insufficient history (cold-start).  ENG-3d-1 and the ML Ensemble
    MUST propagate this flag rather than treating cold-start residuals
    as reliable inputs.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FeatureSetV1STLFields(BaseModel):
    """STL-derived fields contributed by ENG-3c to feature_set_v1.

    Seed for ENG-3d-1 (feature_set_v1 assembly).
    All four feature fields plus the low_data_quality flag are required.
    """

    # The primary residual signal (None when low_data_quality=True)
    stl_residual: float | None = Field(
        default=None,
        description=(
            "Raw STL residual: kwh - trend - seasonal.  "
            "None when low_data_quality=True."
        ),
    )

    # Robust z-score for anomaly severity (None when low_data_quality=True)
    residual_zscore: float | None = Field(
        default=None,
        description=(
            "Robust (MAD-based) z-score of stl_residual within the day-type cohort.  "
            "None when low_data_quality=True."
        ),
    )

    # Absolute magnitude for use as a non-directional feature
    residual_magnitude: float | None = Field(
        default=None,
        description=(
            "abs(stl_residual).  Non-negative.  "
            "None when low_data_quality=True."
        ),
    )

    # Calendar classification (always populated — hard requirement from TRD §3.3)
    day_type: str = Field(
        description=(
            "Building-calendar day classification for this reading.  "
            "One of: business_day | weekend | holiday | declared_closure."
        ),
    )

    # Cold-start propagation flag
    low_data_quality: bool = Field(
        default=False,
        description=(
            "True when the STL layer had insufficient history to produce stable "
            "residuals.  Downstream models must propagate this flag and not treat "
            "None residual fields as zero or as reliable feature values."
        ),
    )

    @classmethod
    def from_stl_result(cls, result: object) -> FeatureSetV1STLFields:
        """Construct from an STLResidualResult without a hard import cycle.

        Uses duck-typed attribute access so models/feature_store/ does not
        import from services/stl_detection/ (which would invert the
        dependency direction).

        Parameters
        ----------
        result:
            An STLResidualResult instance (or any object with the matching
            attributes).
        """
        day_type_val = getattr(result, "day_type", "business_day")
        day_type_str = day_type_val.value if hasattr(day_type_val, "value") else str(day_type_val)
        return cls(
            stl_residual=getattr(result, "stl_residual", None),
            residual_zscore=getattr(result, "residual_zscore", None),
            residual_magnitude=getattr(result, "residual_magnitude", None),
            day_type=day_type_str,
            low_data_quality=bool(getattr(result, "low_data_quality", False)),
        )
