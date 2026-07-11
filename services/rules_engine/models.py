from __future__ import annotations

import datetime
from uuid import UUID

from pydantic import BaseModel, Field

# ExplainabilityBundle (and its RuleCitation sub-model) are the canonical,
# spec-exact contract (TRD v2.0 §3.7) owned by services.explainability.models.
# This module previously defined its own loose, incompatible duplicate of
# both classes — that duplication was a real interface-compatibility bug
# (two classes named ExplainabilityBundle with different, incompatible
# shapes) caught during the pre-ENG-4 integration audit and removed here.
# Every module that persists or reads findings.explainability_bundle must
# use this shared import, never a locally-defined copy.
from services.explainability.models import ExplainabilityBundle, RuleCitation

__all__ = ["ExplainabilityBundle", "Finding", "Rule", "RuleCitation"]


class Rule(BaseModel):
    rule_id: str
    version: int
    effective_date: datetime.date
    author: str
    citation: str
    applies_to: dict[str, str]
    severity: str
    condition: str


class Finding(BaseModel):
    finding_id: UUID
    tenant_id: UUID
    building_id: UUID
    circuit_id: UUID | None = None
    layer_origin: str
    detected_at: datetime.datetime = Field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC)
    )
    evidence_window_start: datetime.datetime
    evidence_window_end: datetime.datetime
    confidence: float | None = None
    status: str = "open"
    explainability_bundle: ExplainabilityBundle
