"""ENG-2d: Scheduled workflow tests.

Tests that:
- Drift detection and retraining schedules register successfully
- Schedules are queryable/describable (visible in Temporal UI)
- Scheduled workflows execute and complete with stub activities
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from temporalio import activity
from temporalio.client import (
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleSpec,
)
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from orchestration.temporal.activities.drift_detection_stub import drift_detection_activity
from orchestration.temporal.activities.retraining_stub import retraining_activity
from orchestration.temporal.dto import ActivityResult, DriftDetectionInput, RetrainingInput
from orchestration.temporal.schedules.drift_detection import (
    register_drift_detection_schedule,
)
from orchestration.temporal.schedules.retraining import register_retraining_schedule
from orchestration.temporal.workflows.drift_detection import DriftDetectionWorkflow
from orchestration.temporal.workflows.retraining import RetrainingWorkflow


# CONFIRMED BUG (pre-ENG-4 integration audit): drift_detection_activity in
# drift_detection_stub.py stopped being a stub once ENG-3e (Drift Detection)
# was integrated -- it now opens a real SQLAlchemy session against a live
# database. The two @pytest.mark.unit tests below that use it (not the
# @pytest.mark.integration ones further down, which use start_local() and a
# different infra tier) predate that merge and were never updated. The
# workflow calls this activity with retry_policy=None, which in the Temporal
# Python SDK means "use the default retry policy" (retries indefinitely) --
# not "no retries." With no database reachable in the test-unit CI job, this
# hung (test-unit ran 50+ minutes with no completion) until this fix. Same
# root cause, same fix pattern as test_analysis_pipeline.py and
# test_signal_query.py's confidence_calibration_activity fix.
@activity.defn(name="drift_detection_activity")
async def mocked_drift_detection_activity(input: DriftDetectionInput) -> ActivityResult:
    return ActivityResult(
        step_name="drift_detection",
        status="completed",
        detail="Mocked drift detection",
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_drift_detection_workflow_executes() -> None:
    """DriftDetectionWorkflow runs end-to-end with stub activity."""
    async with (
        await WorkflowEnvironment.start_time_skipping() as env,
        Worker(
            env.client,
            task_queue="test-queue",
            workflows=[DriftDetectionWorkflow],
            activities=[mocked_drift_detection_activity],
        ),
    ):
        result = await env.client.execute_workflow(
            DriftDetectionWorkflow.run,
            DriftDetectionInput(tenant_id="t-1", building_id="b-1"),
            id="test-drift-exec",
            task_queue="test-queue",
        )
        assert result.step_name == "drift_detection"
        assert result.status == "completed"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_retraining_workflow_executes() -> None:
    """RetrainingWorkflow runs end-to-end with stub activity."""
    async with (
        await WorkflowEnvironment.start_time_skipping() as env,
        Worker(
            env.client,
            task_queue="test-queue",
            workflows=[RetrainingWorkflow],
            activities=[retraining_activity],
        ),
    ):
        result = await env.client.execute_workflow(
            RetrainingWorkflow.run,
            RetrainingInput(tenant_id="t-1", building_id="b-1"),
            id="test-retrain-exec",
            task_queue="test-queue",
        )
        assert result.step_name == "retraining"
        assert result.status == "completed"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_drift_detection_schedule_registers_and_describes() -> None:
    """Schedule is queryable after registration (visible in Temporal UI).

    Uses start_local() which runs a full Temporal dev server supporting
    the Schedule API. The time-skipping test server does not implement
    CreateSchedule (RPCError: unimplemented).
    """
    async with await WorkflowEnvironment.start_local() as env:
        schedule_id = await register_drift_detection_schedule(
            env.client,
            task_queue="test-queue",
            tenant_id="t-sched",
            building_id="b-sched",
        )
        assert schedule_id == "drift-detection-t-sched-b-sched"

        handle = env.client.get_schedule_handle(schedule_id)
        desc = await handle.describe()
        assert desc is not None

        # Clean up
        await handle.delete()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_retraining_schedule_registers_and_describes() -> None:
    """Retraining schedule is queryable after registration.

    Uses start_local() for full Schedule API support.
    """
    async with await WorkflowEnvironment.start_local() as env:
        schedule_id = await register_retraining_schedule(
            env.client,
            task_queue="test-queue",
            tenant_id="t-sched",
            building_id="b-sched",
        )
        assert schedule_id == "retraining-t-sched-b-sched"

        handle = env.client.get_schedule_handle(schedule_id)
        desc = await handle.describe()
        assert desc is not None

        await handle.delete()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_drift_detection_schedule_history_retrievable() -> None:
    """Schedule's underlying workflow history is retrievable.

    Triggers the schedule immediately, waits for one execution,
    and verifies the workflow history is accessible.
    """
    async with (
        await WorkflowEnvironment.start_local() as env,
        Worker(
            env.client,
            task_queue="test-queue",
            workflows=[DriftDetectionWorkflow],
            activities=[drift_detection_activity],
        ),
    ):
        schedule_id = "drift-hist-test"
        await env.client.create_schedule(
            schedule_id,
            Schedule(
                action=ScheduleActionStartWorkflow(
                    DriftDetectionWorkflow.run,
                    DriftDetectionInput(tenant_id="t-hist", building_id="b-hist"),
                    id="drift-hist-wf",
                    task_queue="test-queue",
                ),
                spec=ScheduleSpec(
                    intervals=[ScheduleIntervalSpec(every=timedelta(hours=24))],
                ),
            ),
            trigger_immediately=True,
        )

        # Wait for at least one execution
        import asyncio

        for _ in range(30):
            desc = await env.client.get_schedule_handle(schedule_id).describe()
            if desc.info.num_actions > 0:
                break
            await asyncio.sleep(0.5)

        assert desc.info.num_actions > 0

        # Retrieve workflow history
        wf_handle = env.client.get_workflow_handle("drift-hist-wf")
        history = await wf_handle.fetch_history()
        assert len(history.events) > 0

        await env.client.get_schedule_handle(schedule_id).delete()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_drift_detection_rejects_empty_tenant() -> None:
    """Scheduled workflow validates tenant_id."""
    async with (
        await WorkflowEnvironment.start_time_skipping() as env,
        Worker(
            env.client,
            task_queue="test-queue",
            workflows=[DriftDetectionWorkflow],
            activities=[mocked_drift_detection_activity],
        ),
    ):
        from temporalio.client import WorkflowFailureError

        with pytest.raises(WorkflowFailureError):
            await env.client.execute_workflow(
                DriftDetectionWorkflow.run,
                DriftDetectionInput(tenant_id="", building_id="b-1"),
                id="test-drift-no-tenant",
                task_queue="test-queue",
            )
