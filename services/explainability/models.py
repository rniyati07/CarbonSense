"""ENG-3g-2 — Explainability Bundle data models.

These Pydantic models define the exact JSON contract specified in TRD v2.0 §3.7.
They are the source of truth for what is persisted to findings.explainability_bundle
and consumed downstream by the Reporting Service (TRD §5).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class TopFeature(BaseModel):
    """A SHAP-attributed feature ranked by contribution to a finding."""

    feature: str = Field(..., description="feature_set_v1 feature name")
    shap_value: float = Field(..., description="SHAP value (positive = toward anomaly)")
    plain_language: str = Field(
        ..., description="Human-readable description for a facility manager"
    )


class RuleCitation(BaseModel):
    """A domain rule that fired and contributed to this finding."""

    rule_id: str = Field(..., description="Versioned rule identifier, e.g. hvac_after_hours_v3")
    version: int = Field(..., ge=1, description="Rule version at time of firing")
    citation: str = Field(..., description="Normative reference, e.g. ASHRAE Guideline 36 passage")


class ConfidenceBand(BaseModel):
    """Calibrated confidence interval from Conformal Prediction (ENG-3f)."""

    lower: float = Field(..., ge=0.0, le=1.0)
    upper: float = Field(..., ge=0.0, le=1.0)
    method: Literal["conformal_prediction"] = "conformal_prediction"

    @model_validator(mode="after")
    def lower_lte_upper(self) -> ConfidenceBand:
        if self.lower > self.upper:
            raise ValueError(f"ConfidenceBand.lower ({self.lower}) must be <= upper ({self.upper})")
        return self


class EvidenceWindow(BaseModel):
    """The time interval over which the anomaly signal was observed."""

    start: datetime = Field(..., description="Start of anomaly evidence window (timezone-aware)")
    end: datetime = Field(..., description="End of anomaly evidence window (timezone-aware)")

    @model_validator(mode="after")
    def start_before_end(self) -> EvidenceWindow:
        # A zero-width window (start == end) is legitimate for a domain-rule
        # finding evaluated against a single reading at one timestamp; only a
        # genuinely inverted window (start after end) is a real bug.
        if self.start > self.end:
            raise ValueError(
                f"EvidenceWindow.start ({self.start}) must not be after end ({self.end})"
            )
        return self


# Valid layer identifiers for contributing_layers
VALID_LAYERS = frozenset({"domain_rule", "ml_ensemble", "stl_residual"})


class ExplainabilityBundle(BaseModel):
    """The complete Explainability Bundle (TRD v2.0 §3.7).

    HARD RULES enforced at construction time:
    - top_features and confidence_band are required for any finding whose
      contributing_layers includes "ml_ensemble" and/or "stl_residual" —
      those are the probabilistic layers a SHAP/conformal-prediction result
      exists for.
    - A finding whose contributing_layers is exactly ["domain_rule"] is
      deterministic, not probabilistic (TRD v2.0 §3.2): it has no ML score to
      SHAP-explain and no calibration to bound, so top_features/confidence_band
      may be empty/absent for that case only. This is the documented exception,
      not a general relaxation — any other layer combination still requires both.
    - rule_citations must be a list — never omitted. When contributing_layers
      is ["ml_ensemble"] only, rule_citations MUST be [].
    - contributing_layers must contain at least one valid layer identifier.
    """

    finding_id: UUID
    contributing_layers: list[str] = Field(
        ..., min_length=1, description="Which pipeline layers fired for this finding"
    )
    top_features: list[TopFeature] = Field(
        default_factory=list, description="SHAP-ranked feature contributions"
    )
    rule_citations: list[RuleCitation] = Field(
        default_factory=list,
        description="Domain rules that fired. MUST be [] for ml_ensemble-only findings.",
    )
    confidence_band: ConfidenceBand | None = None
    evidence_window: EvidenceWindow

    @field_validator("contributing_layers")
    @classmethod
    def validate_layers(cls, v: list[str]) -> list[str]:
        unknown = set(v) - VALID_LAYERS
        if unknown:
            raise ValueError(f"Unknown contributing layers: {unknown}")
        return v

    @model_validator(mode="after")
    def enforce_rule_citation_invariant(self) -> ExplainabilityBundle:
        """ml_ensemble-only findings must have rule_citations = [], not omitted."""
        is_ml_only = set(self.contributing_layers) == {"ml_ensemble"}
        if is_ml_only and self.rule_citations:
            raise ValueError(
                "contributing_layers=['ml_ensemble'] only: rule_citations must be []"
                " — do not add rule citations when no rule fired."
            )
        return self

    @model_validator(mode="after")
    def enforce_probabilistic_fields_for_ml_or_stl(self) -> ExplainabilityBundle:
        """top_features/confidence_band are required unless the finding is
        domain_rule-only (deterministic — no ML score exists to explain or
        calibrate)."""
        is_rule_only = set(self.contributing_layers) == {"domain_rule"}
        if not is_rule_only:
            if not self.top_features:
                raise ValueError(
                    "top_features must be non-empty for any finding whose "
                    "contributing_layers includes ml_ensemble and/or stl_residual."
                )
            if self.confidence_band is None:
                raise ValueError(
                    "confidence_band is required for any finding whose "
                    "contributing_layers includes ml_ensemble and/or stl_residual."
                )
        return self
