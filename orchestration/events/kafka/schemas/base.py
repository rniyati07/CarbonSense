from __future__ import annotations

import datetime
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class BaseEvent:
    """Base for all Kafka events.

    Every event carries tenant_id, building_id, correlation_id, event_id,
    and timestamp per ENG-2b contract.
    """

    event_id: UUID
    tenant_id: UUID
    building_id: UUID
    correlation_id: UUID
    timestamp: datetime.datetime
    event_type: str
