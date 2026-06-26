from __future__ import annotations

import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class RuleCitation(BaseModel):
    rule_id: str
    version: int
    citation: str
    severity: str
    matched_condition: str


class Rule(BaseModel):
    rule_id: str
    version: int
    effective_date: datetime.date
    author: str
    citation: str
    applies_to: dict[str, str]
    severity: str
    condition: str


class ExplainabilityBundle(BaseModel):
    finding_id: UUID | None = None
    contributing_layers: list[str] = Field(default_factory=list)
    top_features: list[dict] = Field(default_factory=list)
    rule_citations: list[RuleCitation] = Field(default_factory=list)
    confidence_band: dict[str, float | str] | None = None
    evidence_window: dict[str, datetime.datetime | str] | None = None


class Finding(BaseModel):
    finding_id: UUID | None = None
    tenant_id: UUID
    building_id: UUID
    circuit_id: UUID | None = None
    layer_origin: str
    detected_at: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    evidence_window_start: datetime.datetime
    evidence_window_end: datetime.datetime
    confidence: float | None = None
    status: str = "open"
    explainability_bundle: ExplainabilityBundle
