from __future__ import annotations

from datetime import timedelta

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleSpec,
)

from orchestration.temporal.dto import DriftDetectionInput
from orchestration.temporal.workflows.drift_detection import DriftDetectionWorkflow


async def register_drift_detection_schedule(
    client: Client,
    task_queue: str,
    tenant_id: str,
    building_id: str,
) -> str:
    """Register a nightly drift detection schedule for a building."""
    schedule_id = f"drift-detection-{tenant_id}-{building_id}"
    await client.create_schedule(
        schedule_id,
        Schedule(
            action=ScheduleActionStartWorkflow(
                DriftDetectionWorkflow.run,
                DriftDetectionInput(tenant_id=tenant_id, building_id=building_id),
                id=f"drift-{tenant_id}-{building_id}",
                task_queue=task_queue,
            ),
            spec=ScheduleSpec(
                intervals=[ScheduleIntervalSpec(every=timedelta(hours=24))],
            ),
        ),
    )
    return schedule_id
