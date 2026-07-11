"""TRD §5 — Explainability & Reporting Service data models.

These Pydantic models define:
- The input payload to the Reporting Service (ReportingRequest)
- The LLM output schema (ActionPlan, ActionItem)
- The Optimization Scenario contract mirror (OptimizationScenario)

The ActionPlan is the single source of truth — the PDF is a template over this
object, not an independently maintained artifact (TRD v2.0 §5.4).
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from services.explainability.models import ExplainabilityBundle

# ---------------------------------------------------------------------------
# Input: what the Reporting Service receives
# ---------------------------------------------------------------------------


class OptimizationScenario(BaseModel):
    """Mirror of the Optimization Engine output contract (TRD v2.0 §4)."""

    scenario_id: UUID
    scenario_model: str = Field(..., description="e.g. load_shift_v1")
    model_version: int = Field(..., ge=1)
    building_id: UUID
    justifying_finding_ids: list[UUID] = Field(
        ..., min_length=1, description="Finding IDs that justify this scenario"
    )
    baseline_kwh: float = Field(..., ge=0)
    optimized_kwh: float = Field(..., ge=0)
    baseline_emissions_kg_co2: float = Field(..., ge=0)
    optimized_emissions_kg_co2: float = Field(..., ge=0)
    pct_reduction: float = Field(..., ge=0, le=100)
    estimated_annual_savings_inr: float = Field(..., ge=0)
    payback_months: float = Field(..., ge=0)
    confidence_band: dict[str, float] = Field(
        default_factory=dict,
        description="{'lower_pct': ..., 'upper_pct': ...}",
    )
    bounds_check: Literal["passed", "failed"] = "passed"


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
