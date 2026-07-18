"""ENG-4 — Optimization Engine data models.

OptimizationScenario is the canonical TRD v2.0 §4 output contract, owned
here.  services/reporting/models.py previously carried its own hand-written
"mirror" of this exact shape (predating ENG-4's real implementation) --
that duplication is retired as part of this epic; services/reporting now
imports OptimizationScenario from here instead of maintaining a second copy.
"""

from __future__ import annotations

import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class OptimizationScenario(BaseModel):
    """A single generated scenario -- the exact TRD v2.0 §4 output contract."""

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
    confidence_band: dict[str, float] = Field(
        default_factory=dict,
        description="{'lower_pct': ..., 'upper_pct': ...}",
    )
    estimated_annual_savings_inr: float = Field(..., ge=0)
    payback_months: float = Field(..., ge=0)
    bounds_check: Literal["passed", "failed"] = "passed"


class ScenarioUnavailable(BaseModel):
    """Explicit, non-fabricated result when a scenario model has no
    justifying finding or fails its applicability gate (TRD v2.0 §4 /
    ENG-4c: "If none exist, return an explicit 'no justified scenario
    available'" -- never a generic template)."""

    scenario_model: str
    model_version: int = Field(..., ge=1)
    building_id: UUID
    reason: str


ScenarioOutcome = OptimizationScenario | ScenarioUnavailable


class ModelQualityIncident(BaseModel):
    """A scenario result that failed the ENG-4d bounds-enforcement
    invariant -- rejected, not silently clipped, and persisted here as a
    structured incident (see database/migrations/versions/0007)."""

    incident_id: UUID
    tenant_id: UUID
    building_id: UUID
    scenario_model: str
    incident_type: str
    severity: Literal["warning", "critical"] = "warning"
    message: str
    metadata: dict[str, object] = Field(default_factory=dict)
    created_at: datetime.datetime


class PortfolioScenarioRollup(BaseModel):
    """One scenario_model's aggregation across every building in a
    portfolio request that produced a valid scenario for it (TRD v2.0 §4:
    "a query-shape addition, not a separate service" -- this is pure
    aggregation over independently-computed per-building results, no LP
    reformulation across buildings)."""

    scenario_model: str
    model_version: int = Field(..., ge=1)
    contributing_building_ids: list[UUID] = Field(..., min_length=1)
    total_baseline_kwh: float = Field(..., ge=0)
    total_optimized_kwh: float = Field(..., ge=0)
    total_baseline_emissions_kg_co2: float = Field(..., ge=0)
    total_optimized_emissions_kg_co2: float = Field(..., ge=0)
    pct_reduction: float = Field(..., ge=0, le=100)
    total_estimated_annual_savings_inr: float = Field(..., ge=0)


class PortfolioOptimizationResult(BaseModel):
    """Result of a multi-building optimization request (ENG-4e)."""

    building_ids: list[UUID] = Field(..., min_length=1)
    per_building: dict[UUID, list[ScenarioOutcome]]
    rollups: list[PortfolioScenarioRollup]
