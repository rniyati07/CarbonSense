from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class CalibrationInput(BaseModel):
    tenant_id: UUID
    building_id: UUID
    correlation_id: str


class UncalibratedFinding(BaseModel):
    finding_id: UUID
    circuit_id: UUID | None
    ml_anomaly_score: float
    stl_residual: float | None = None
    rule_flags: list[str] = Field(default_factory=list)


class FeedbackLabel(BaseModel):
    action: Literal["confirmed", "dismissed"]
    ml_anomaly_score: float


class CalibratedFinding(BaseModel):
    finding_id: UUID
    confidence_interval_lower: float
    confidence_interval_upper: float
    confidence_label: str
