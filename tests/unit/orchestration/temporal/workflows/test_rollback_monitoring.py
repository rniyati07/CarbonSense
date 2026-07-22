"""Mirrors tests/unit/orchestration/temporal/workflows/test_drift_detection.py's
established WorkflowEnvironment pattern."""

from __future__ import annotations

import pytest
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from orchestration.temporal.dto import ActivityResult, RollbackCheckInput, RollbackMonitoringInput
from orchestration.temporal.workflows.rollback_monitoring import RollbackMonitoringWorkflow


@activity.defn(name="rollback_check_activity")
async def mocked_rollback_check_activity(input: RollbackCheckInput) -> ActivityResult:
    return ActivityResult(
        step_name="rollback_check",
        status="completed",
        detail=f"rolled_back=False: {input.model_type} within ceiling",
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_rollback_monitoring_workflow_checks_both_model_types() -> None:
    async with (
        await WorkflowEnvironment.start_time_skipping() as env,
        Worker(
            env.client,
            task_queue="test-queue",
            workflows=[RollbackMonitoringWorkflow],
            activities=[mocked_rollback_check_activity],
        ),
    ):
        results = await env.client.execute_workflow(
            RollbackMonitoringWorkflow.run,
            RollbackMonitoringInput(
                tenant_id="123e4567-e89b-12d3-a456-426614174000",
                building_id="123e4567-e89b-12d3-a456-426614174001",
            ),
            id="test-rollback-monitoring-workflow",
            task_queue="test-queue",
        )

    assert len(results) == 2
    checked_model_types = {r.detail.split(": ")[1].split(" ")[0] for r in results}
    assert checked_model_types == {"isolation_forest", "autoencoder"}
    assert all(r.status == "completed" for r in results)
