import pytest
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from orchestration.temporal.dto import ActivityResult, DriftDetectionInput
from orchestration.temporal.workflows.drift_detection import DriftDetectionWorkflow


# CONFIRMED BUGS (pre-ENG-4 integration audit) fixed in this file:
# 1. start_time_skipping() returns a coroutine that must be awaited before
#    it can be used as an async context manager -- every other Temporal test
#    in this repo (test_hello_world.py etc.) does `await WorkflowEnvironment.
#    start_time_skipping() as env`.
# 2. `WorkflowEnvironment.activity(...)` is not a real API (no such method
#    exists on WorkflowEnvironment); mock activities are plain @activity.defn
#    functions passed to Worker(activities=[...]), same as every other
#    Temporal test in this repo.
# Neither bug was ever caught because the drift_detection package's own
# import chain had a real SyntaxError (see repository.py) that made this
# test file uncollectible.
@activity.defn(name="drift_detection_activity")
async def mocked_drift_detection_activity(input: DriftDetectionInput) -> ActivityResult:
    return ActivityResult(
        step_name="drift_detection",
        status="completed",
        detail="Drift detected: increasing",
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_drift_detection_workflow():
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
            DriftDetectionInput(
                tenant_id="123e4567-e89b-12d3-a456-426614174000",
                building_id="123e4567-e89b-12d3-a456-426614174001",
            ),
            id="test-drift-workflow",
            task_queue="test-queue",
        )

        assert result.step_name == "drift_detection"
        assert result.status == "completed"
        assert "Drift detected" in result.detail
