"""TRD §5 — Explainability & Reporting Service data models.

These Pydantic models define:
- The input payload to the Reporting Service (ReportingRequest)
- The LLM output schema (ActionPlan, ActionItem)

OptimizationScenario used to be hand-mirrored here, predating ENG-4's real
implementation. It is now owned by services.optimization.models (the
service that actually produces it) and re-exported here for backward
compatibility with this module's existing public API.

The ActionPlan is the single source of truth — the PDF is a template over this
object, not an independently maintained artifact (TRD v2.0 §5.4).
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from services.explainability.models import ExplainabilityBundle
from services.optimization.models import OptimizationScenario  # noqa: F401 (re-exported)

# ---------------------------------------------------------------------------
# Input: what the Reporting Service receives
# ---------------------------------------------------------------------------


class FindingWithBundle(BaseModel):
    """A finding paired with its Explainability Bundle for reporting."""

    finding_id: UUID
    building_id: UUID
    circuit_id: UUID | None = None
    layer_origin: str = Field(..., description="Comma-separated layers that produced this finding")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Calibrated confidence")
    explainability_bundle: ExplainabilityBundle


class ReportingRequest(BaseModel):
    """Input to the Reporting Service — one or more findings + optimization scenarios."""

    findings: list[FindingWithBundle] = Field(..., min_length=1)
    optimization_scenarios: list[OptimizationScenario] = Field(
        default_factory=list,
        description="Scenarios linked to the findings. May be empty on first pass.",
    )
    building_name: str = Field(default="Building")
    tenant_id: UUID | None = None


# ---------------------------------------------------------------------------
# Output: what the Reporting Service produces (LLM output schema)
# ---------------------------------------------------------------------------

EffortLevel = Literal["Low", "Medium", "High"]


class ActionItem(BaseModel):
    """A single recommended action in the Carbon Action Plan."""

    title: str
    description: str = Field(..., description="<=50 words, plain language")
    justifying_finding_ids: list[UUID] = Field(
        ..., min_length=1, description="Finding IDs from the input payload that justify this action"
    )
    estimated_co2_saved_kg_per_year: float = Field(..., ge=0)
    estimated_savings_inr_per_year: float = Field(..., ge=0)
    effort_level: EffortLevel
    payback_months: float = Field(..., ge=0)
    confidence_note: str = Field(
        ..., description="Honest description of confidence derived from confidence_band"
    )


class ActionPlan(BaseModel):
    """The Carbon Action Plan — single source of truth for both API response and PDF.

    Produced either by the LLM narrator or, on double failure, by the deterministic
    FallbackNarrator. The schema is identical in both cases (TRD v2.0 §5.3).
    """

    narrative_summary: str = Field(
        ..., description="<=100 words, plain language, references confidence honestly"
    )
    actions: list[ActionItem] = Field(default_factory=list)
    generated_by: Literal["llm", "fallback"] = "llm"
