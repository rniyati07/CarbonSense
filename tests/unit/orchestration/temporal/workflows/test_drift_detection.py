import pytest
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from orchestration.temporal.dto import ActivityResult, DriftDetectionInput
from orchestration.temporal.workflows.drift_detection import DriftDetectionWorkflow
from orchestration.temporal.activities.drift_detection_stub import drift_detection_activity


@pytest.mark.unit
@pytest.mark.asyncio
async def test_drift_detection_workflow():
    async with WorkflowEnvironment.start_time_skipping() as env:

        # We need a mocked activity since the real one connects to DB.
        # The mock name must match the @activity.defn function name exactly,
        # which Temporal uses as the registered activity type name.
        @env.activity(name="drift_detection_activity")
        async def mocked_activity(input: DriftDetectionInput) -> ActivityResult:
            return ActivityResult(
                step_name="drift_detection",
                status="completed",
                detail="Drift detected: increasing"
            )

        async with Worker(
            env.client,
            task_queue="test-queue",
            workflows=[DriftDetectionWorkflow],
            activities=[mocked_activity],
        ):
            result = await env.client.execute_workflow(
                DriftDetectionWorkflow.run,
                DriftDetectionInput(tenant_id="123e4567-e89b-12d3-a456-426614174000", building_id="123e4567-e89b-12d3-a456-426614174001"),
                id="test-drift-workflow",
                task_queue="test-queue",
            )
            
            assert result.step_name == "drift_detection"
            assert result.status == "completed"
            assert "Drift detected" in result.detail
