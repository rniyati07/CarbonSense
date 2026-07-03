from __future__ import annotations

import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel

class DriftStatus(str, Enum):
    STABLE = "stable"
    DRIFTING = "drifting"

class TrendDirection(str, Enum):
    INCREASING = "increasing"
    DECREASING = "decreasing"
    NONE = "none"

class DriftResult(BaseModel):
    """The result of a building-level drift detection evaluation."""
    tenant_id: UUID
    building_id: UUID
    status: DriftStatus
    trend_direction: TrendDirection
    magnitude: Optional[float] = None
    evaluated_at: datetime.datetime

class DriftEventPayload(BaseModel):
    """Payload for the `model.drift.detected` Kafka event."""
    tenant_id: UUID
    building_id: UUID
    trend_direction: TrendDirection
    magnitude: Optional[float]
    timestamp: datetime.datetime
