"""ENG-6d — schedule registration for RollbackMonitoringWorkflow.
Mirrors orchestration/temporal/schedules/retraining.py's shape exactly.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleSpec,
)

from orchestration.temporal.dto import RollbackMonitoringInput
from orchestration.temporal.workflows.rollback_monitoring import RollbackMonitoringWorkflow


async def register_rollback_monitoring_schedule(
    client: Client,
    task_queue: str,
    tenant_id: str,
    building_id: str,
) -> str:
    """Register a daily post-promotion false-positive-rate check for a
    building (TRD v2.0 §6.4). Daily, not monthly like the calendar
    retraining cadence -- a regression must be caught promptly, not on
    the next retraining cycle."""
    schedule_id = f"rollback-monitoring-{tenant_id}-{building_id}"
    await client.create_schedule(
        schedule_id,
        Schedule(
            action=ScheduleActionStartWorkflow(
                RollbackMonitoringWorkflow.run,
                RollbackMonitoringInput(tenant_id=tenant_id, building_id=building_id),
                id=f"rollback-check-{tenant_id}-{building_id}",
                task_queue=task_queue,
            ),
            spec=ScheduleSpec(
                intervals=[ScheduleIntervalSpec(every=timedelta(days=1))],
            ),
        ),
    )
    return schedule_id
