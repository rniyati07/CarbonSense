from __future__ import annotations

import datetime
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


class CalibratedScore(BaseModel):
    """ENG-2c-wiring addition: the calibrate_ensemble_scores() entry point's
    return shape -- one reading's calibrated confidence band, keyed by
    (circuit_id, ts) rather than finding_id, since no Finding/finding_id
    exists yet at this point in the pipeline (Root-Cause Attribution, which
    runs after Confidence Calibration, is what creates the Finding).
    """

    circuit_id: UUID
    ts: datetime.datetime
    confidence_lower: float
    confidence_upper: float
    is_cold_start: bool
