from __future__ import annotations

from dataclasses import dataclass

from orchestration.events.kafka.schemas.base import BaseEvent


@dataclass(frozen=True)
class RetrainingEligibleEvent(BaseEvent):
    """Published when a building's new feedback count crosses the retraining threshold.

    Security Note for ENG-6:
    When consuming this event, the retraining worker MUST run its training-data queries
    through a Row Level Security (RLS) enforced database session. Specifically, it must
    set `app.current_tenant_id` to this event's `tenant_id` before querying, ensuring
    strict multi-tenant database isolation.
    """

    feedback_count: int
    retraining_threshold: int
