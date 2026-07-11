"""ENG-3c-2 / ENG-3d-1 — Canonical feature_set_v1 contract.

Status: COMPLETE — ENG-3d-1
--------------------------------------------------------
This module defines the single canonical feature contract consumed by:
    - ML Ensemble (ENG-3d): Isolation Forest + Windowed Autoencoder
    - Confidence Calibration (ENG-3f)
    - Root-Cause Attribution / SHAP (ENG-3g)
    - GNN research track (RES-3a, by direct reuse per DATA_AND_MODEL_STRATEGY §9.1)

Do NOT create a divergent copy of this schema in any other service.
Import from models.feature_store.feature_set_v1 wherever feature_set_v1
fields are needed.

Why this file exists here (not in services/stl_detection/ or services/ml_ensemble/)
------------------------------------------------------------------------------------
DATA_AND_MODEL_STRATEGY §3.7 specifies that feature_set_v1 lives under
models/feature_store/ and is defined once.  Multiple services consume it.
Placing it in a service module would invert the dependency direction.

Feature groups in FeatureSetV1 (ENG-3d-1)
------------------------------------------
Rolling statistics (DATA_AND_MODEL_STRATEGY §3.2):
    rolling_baseline_kwh        — rolling mean of hourly kWh
    peak_offpeak_split          — ratio of peak-hour kWh to total kWh in window
    after_hours_kwh_ratio       — ratio of after-hours to in-hours consumption
    weekend_floor_load          — weekend after-hours baseline
    rolling_efficiency_ratio    — actual / rolling_baseline (Drift Detection input)

STL-derived features (ENG-3c-2 / DATA_AND_MODEL_STRATEGY §3.7):
    stl_residual_magnitude      — abs(stl_residual), non-negative magnitude
    day_type                    — calendar classification

Calendar features:
    day_type already embedded from STL fields.

Rule Engine outputs (DATA_AND_MODEL_STRATEGY §3.7):
    rule_fire_indicators        — dict of rule_id → bool (True if fired)

Data-quality propagation:
    low_data_quality            — True when STL could not produce stable residuals

Version string (ENG-3d-1 requirement):
    FEATURE_SCHEMA_VERSION = "feature_set_v1"

STL-field compatibility layer:
    FeatureSetV1STLFields is preserved for ENG-3c compatibility.
"""

from __future__ import annotations

import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Version string — required by ENG-3d-1 spec.
# All code that serialises or deserialises a feature vector MUST embed this
# string so mismatches between training and serving can be detected.
# ---------------------------------------------------------------------------

FEATURE_SCHEMA_VERSION: str = "feature_set_v1"

# ---------------------------------------------------------------------------
# Day-type encoding — consistent ordering for numeric feature vectors.
# ---------------------------------------------------------------------------

DAY_TYPE_ENCODING: dict[str, int] = {
    "business_day": 0,
    "weekend": 1,
    "holiday": 2,
    "declared_closure": 3,
}


# ---------------------------------------------------------------------------
# FeatureSetV1STLFields — ENG-3c-2 seed (preserved for backwards compat)
# ---------------------------------------------------------------------------


class FeatureSetV1STLFields(BaseModel):
    """STL-derived fields contributed by ENG-3c to feature_set_v1.

    Preserved for ENG-3c compatibility.  ENG-3d-1 extended this file with
    the full FeatureSetV1 below; FeatureSetV1STLFields remains unchanged.
    """

    # The primary residual signal (None when low_data_quality=True)
    stl_residual: float | None = Field(
        default=None,
        description=("Raw STL residual: kwh - trend - seasonal.  None when low_data_quality=True."),
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
        description=("abs(stl_residual).  Non-negative.  None when low_data_quality=True."),
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


# ---------------------------------------------------------------------------
# FeatureSetV1 — the complete canonical feature contract (ENG-3d-1)
# ---------------------------------------------------------------------------


class FeatureSetV1(BaseModel):
    """Versioned, canonical feature contract consumed by the ML Ensemble.

    ENG-3d-1 requirement: one definition, versioned, no divergent copies.

    All numeric fields carry sentinel None to distinguish "not available"
    from zero.  Callers building a feature matrix must handle None
    explicitly (see to_numeric_vector()).

    The rule_fire_indicators dict maps each rule_id active for this
    building to a boolean (True = rule fired for this reading/window).
    The dict may be empty for buildings with no active rules — that is a
    valid state, not an error.
    """

    # Schema version — embed in every serialised row/artifact so mismatches
    # between training and serving can be detected at load time.
    feature_schema_version: str = Field(
        default=FEATURE_SCHEMA_VERSION,
        description="Schema version string.  Always 'feature_set_v1' for this class.",
    )

    # Identity fields (not used as ML features, but needed for traceability)
    tenant_id: UUID
    circuit_id: UUID
    ts: datetime.datetime

    # ------------------------------------------------------------------ #
    # Rolling statistics  (DATA_AND_MODEL_STRATEGY §3.2)
    # ------------------------------------------------------------------ #

    rolling_baseline_kwh: float | None = Field(
        default=None,
        description=(
            "Rolling mean of hourly kWh over a trailing window.  "
            "IMPLEMENTATION DEFAULT: 7-day window (DATA_AND_MODEL_STRATEGY §3.2 "
            "specifies 7-day and 30-day variants — confirm window with ML Lead "
            "before production deployment)."
        ),
    )

    peak_offpeak_split: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "Ratio of peak-hour kWh to total kWh in the rolling window.  "
            "Declared peak hours come from building metadata."
        ),
    )

    after_hours_kwh_ratio: float | None = Field(
        default=None,
        ge=0.0,
        description=(
            "Ratio of after-hours kWh to in-hours kWh.  "
            "Used by the Domain Rule Engine (hvac_after_hours_v3) and SHAP attribution."
        ),
    )

    weekend_floor_load: float | None = Field(
        default=None,
        ge=0.0,
        description=(
            "Weekend after-hours kWh floor divided by weekday after-hours baseline.  "
            "Used by the Domain Rule Engine (weekend_vampire_load_v1)."
        ),
    )

    rolling_efficiency_ratio: float | None = Field(
        default=None,
        ge=0.0,
        description=(
            "Actual kWh divided by rolling_baseline_kwh.  "
            "Input to Drift Detection (Mann-Kendall, ENG-3e).  "
            "Values > 1 indicate above-baseline consumption."
        ),
    )

    # ------------------------------------------------------------------ #
    # STL-derived features  (ENG-3c-2 / DATA_AND_MODEL_STRATEGY §3.7)
    # ------------------------------------------------------------------ #

    stl_residual_magnitude: float | None = Field(
        default=None,
        ge=0.0,
        description=(
            "Absolute magnitude of the STL residual component: abs(kwh - trend - seasonal).  "
            "None when low_data_quality=True (cold-start or insufficient history)."
        ),
    )

    # Calendar classification — also in STLFields; canonical version lives here.
    day_type: str = Field(
        default="business_day",
        description=(
            "Building-calendar day classification.  "
            "One of: business_day | weekend | holiday | declared_closure.  "
            "Used by STL cohort decomposition and as a categorical ML feature."
        ),
    )

    # ------------------------------------------------------------------ #
    # Rule Engine outputs  (DATA_AND_MODEL_STRATEGY §3.7)
    # ------------------------------------------------------------------ #

    rule_fire_indicators: dict[str, bool] = Field(
        default_factory=dict,
        description=(
            "Binary indicator per active rule_id for this building.  "
            "True if the rule fired for this reading/window; False otherwise.  "
            "The dict may be empty for buildings with no active rules.  "
            "Key ordering is not guaranteed — use to_numeric_vector(rule_ids) "
            "for a consistently-ordered feature vector."
        ),
    )

    # ------------------------------------------------------------------ #
    # Data-quality propagation  (TRD §2.4, §3.4)
    # ------------------------------------------------------------------ #

    low_data_quality: bool = Field(
        default=False,
        description=(
            "True when the STL layer had insufficient history (cold-start).  "
            "ML Ensemble and downstream layers must propagate this flag and "
            "apply down-weighting / wide confidence bands accordingly."
        ),
    )

    # ------------------------------------------------------------------ #
    # Feature vector serialisation
    # ------------------------------------------------------------------ #

    def to_numeric_vector(self, rule_ids: list[str]) -> list[float]:
        """Return a consistently-ordered float list for use as a feature row.

        Parameters
        ----------
        rule_ids:
            Ordered list of rule_ids whose indicators should be included.
            Must match the list stored in the BuildingScaler so training
            and inference produce identical feature orderings.

        Returns
        -------
        list[float]
            Ordered as:
              [rolling_baseline_kwh, peak_offpeak_split, after_hours_kwh_ratio,
               weekend_floor_load, rolling_efficiency_ratio,
               stl_residual_magnitude, day_type_encoded,
               rule_fire_<rule_id_0>, ..., rule_fire_<rule_id_N>]

            None fields are encoded as 0.0 so the vector is always finite.
            Callers that need to propagate low_data_quality should inspect
            that flag separately rather than relying on zero-fill behaviour.
        """
        day_enc = float(DAY_TYPE_ENCODING.get(self.day_type, 0))
        rule_flags = [1.0 if self.rule_fire_indicators.get(rid, False) else 0.0 for rid in rule_ids]
        return [
            self.rolling_baseline_kwh if self.rolling_baseline_kwh is not None else 0.0,
            self.peak_offpeak_split if self.peak_offpeak_split is not None else 0.0,
            self.after_hours_kwh_ratio if self.after_hours_kwh_ratio is not None else 0.0,
            self.weekend_floor_load if self.weekend_floor_load is not None else 0.0,
            self.rolling_efficiency_ratio if self.rolling_efficiency_ratio is not None else 0.0,
            self.stl_residual_magnitude if self.stl_residual_magnitude is not None else 0.0,
            day_enc,
            *rule_flags,
        ]

    @classmethod
    def base_feature_names(cls) -> list[str]:
        """Return the ordered names of the base (non-rule) features."""
        return [
            "rolling_baseline_kwh",
            "peak_offpeak_split",
            "after_hours_kwh_ratio",
            "weekend_floor_load",
            "rolling_efficiency_ratio",
            "stl_residual_magnitude",
            "day_type_encoded",
        ]

    @classmethod
    def feature_names(cls, rule_ids: list[str]) -> list[str]:
        """Return full ordered feature names for a given rule_ids list."""
        return cls.base_feature_names() + [f"rule_fire_{rid}" for rid in rule_ids]

    @classmethod
    def from_components(
        cls,
        *,
        tenant_id: UUID,
        circuit_id: UUID,
        ts: datetime.datetime,
        rolling_baseline_kwh: float | None,
        peak_offpeak_split: float | None,
        after_hours_kwh_ratio: float | None,
        weekend_floor_load: float | None,
        rolling_efficiency_ratio: float | None,
        stl_fields: FeatureSetV1STLFields | None,
        rule_fire_indicators: dict[str, bool] | None,
    ) -> FeatureSetV1:
        """Convenience constructor used by the Feature Assembly service.

        Merges rolling statistics, STL fields, and rule-fire indicators
        into a single canonical FeatureSetV1 instance.
        """
        stl_mag: float | None = None
        day_type_str: str = "business_day"
        low_qual: bool = False

        if stl_fields is not None:
            stl_mag = stl_fields.residual_magnitude
            day_type_str = stl_fields.day_type
            low_qual = stl_fields.low_data_quality

        return cls(
            tenant_id=tenant_id,
            circuit_id=circuit_id,
            ts=ts,
            rolling_baseline_kwh=rolling_baseline_kwh,
            peak_offpeak_split=peak_offpeak_split,
            after_hours_kwh_ratio=after_hours_kwh_ratio,
            weekend_floor_load=weekend_floor_load,
            rolling_efficiency_ratio=rolling_efficiency_ratio,
            stl_residual_magnitude=stl_mag,
            day_type=day_type_str,
            rule_fire_indicators=rule_fire_indicators or {},
            low_data_quality=low_qual,
        )

    def model_post_init(self, __context: Any) -> None:
        if self.feature_schema_version != FEATURE_SCHEMA_VERSION:
            raise ValueError(
                f"feature_schema_version mismatch: expected {FEATURE_SCHEMA_VERSION!r}, "
                f"got {self.feature_schema_version!r}"
            )
