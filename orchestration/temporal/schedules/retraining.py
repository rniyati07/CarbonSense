from __future__ import annotations

from datetime import timedelta

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleSpec,
)

from orchestration.temporal.dto import RetrainingInput
from orchestration.temporal.workflows.retraining import RetrainingWorkflow


async def register_retraining_schedule(
    client: Client,
    task_queue: str,
    tenant_id: str,
    building_id: str,
) -> str:
    """Register a monthly retraining schedule for a building."""
    schedule_id = f"retraining-{tenant_id}-{building_id}"
    await client.create_schedule(
        schedule_id,
        Schedule(
            action=ScheduleActionStartWorkflow(
                RetrainingWorkflow.run,
                RetrainingInput(
                    tenant_id=tenant_id,
                    building_id=building_id,
                    trigger="calendar",
                ),
                id=f"retrain-{tenant_id}-{building_id}",
                task_queue=task_queue,
            ),
            spec=ScheduleSpec(
                intervals=[ScheduleIntervalSpec(every=timedelta(days=30))],
            ),
        ),
    )
    return schedule_id
