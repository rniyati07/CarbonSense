"""ENG-2c: Analysis pipeline workflow tests.

DoD: End-to-end execution using stub activities, tenant_id validation,
and human signal received causing workflow resume and completion.
"""

from __future__ import annotations

import pytest
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from orchestration.temporal.activities.analysis_stubs import (
    data_quality_gate_activity,
    feature_assembly_activity,
    ml_ensemble_activity,
    root_cause_attribution_activity,
    rule_engine_activity,
    stl_detection_activity,
)
from orchestration.temporal.dto import (
    ActivityResult,
    AnalysisPipelineInput,
    HumanReviewSignal,
)
from orchestration.temporal.workflows.analysis_pipeline import AnalysisPipelineWorkflow


# CONFIRMED BUG (pre-ENG-4 integration audit): confidence_calibration_activity
# in analysis_stubs.py stopped being a stub once ENG-3f (Confidence Calibration)
# was integrated -- it now opens a real SQLAlchemy session against a live
# database (see analysis_stubs.py). This test file predates that merge and
# was never updated: it imported the real activity into ALL_ACTIVITIES, and
# the workflow calls it with no retry_policy (Temporal's default retries
# indefinitely). With no database reachable in this test environment, every
# attempt fails and the workflow retries forever -- this hung both locally
# and in CI (test-unit ran 50+ minutes with no completion) until this fix.
#
# ENG-2c's own documented DoD for this workflow is "runs end-to-end... with
# stubbed layer calls" -- this test exists to verify orchestration (sequencing,
# parallel execution, signal/human-review-wait), not confidence_calibration's
# real business logic, which has its own coverage in
# tests/unit/services/calibration/. Restoring a stub here, registered under
# the same activity name so the workflow's execute_activity(...) call routes
# to it, is the correct fix -- not adding a retry_policy (that would still
# eventually fail against a real DB error, just faster; the point is this
# workflow test shouldn't touch a database at all).
@activity.defn(name="confidence_calibration_activity")
async def mocked_confidence_calibration_activity(
    input: AnalysisPipelineInput,
) -> ActivityResult:
    return ActivityResult(
        step_name="confidence_calibration",
        status="completed",
        detail=f"Mocked calibration for tenant={input.tenant_id}",
    )


ALL_ACTIVITIES = [
    data_quality_gate_activity,
    rule_engine_activity,
    stl_detection_activity,
    feature_assembly_activity,
    ml_ensemble_activity,
    mocked_confidence_calibration_activity,
    root_cause_attribution_activity,
]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pipeline_end_to_end_with_signal() -> None:
    """Full pipeline: all stubs execute, signal completes the workflow."""
    async with (
        await WorkflowEnvironment.start_time_skipping() as env,
        Worker(
            env.client,
            task_queue="test-queue",
            workflows=[AnalysisPipelineWorkflow],
            activities=ALL_ACTIVITIES,
        ),
    ):
        handle = await env.client.start_workflow(
            AnalysisPipelineWorkflow.run,
            AnalysisPipelineInput(
                tenant_id="tenant-1",
                building_id="building-1",
                correlation_id="corr-1",
            ),
            id="test-pipeline-e2e",
            task_queue="test-queue",
        )

        # Wait until the workflow reaches human review
        import asyncio

        for _ in range(100):
            status = await handle.query(AnalysisPipelineWorkflow.get_status)
            if status.is_waiting_for_human_review:
                break
            await asyncio.sleep(0.1)

        assert status.is_waiting_for_human_review is True
        assert "root_cause_attribution" in status.steps_completed

        # Send the human review signal
        await handle.signal(
            AnalysisPipelineWorkflow.human_review_completed,
            HumanReviewSignal(
                reviewer_id="reviewer-1",
                action="approved",
                comment="Looks good",
            ),
        )

        result = await handle.result()
        assert "completed" in result.lower()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pipeline_rejects_empty_tenant_id() -> None:
    """Workflow must reject execution if tenant_id is missing."""
    async with (
        await WorkflowEnvironment.start_time_skipping() as env,
        Worker(
            env.client,
            task_queue="test-queue",
            workflows=[AnalysisPipelineWorkflow],
            activities=ALL_ACTIVITIES,
        ),
    ):
        with pytest.raises(WorkflowFailureError):
            await env.client.execute_workflow(
                AnalysisPipelineWorkflow.run,
                AnalysisPipelineInput(
                    tenant_id="",
                    building_id="building-1",
                    correlation_id="corr-1",
                ),
                id="test-pipeline-no-tenant",
                task_queue="test-queue",
            )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pipeline_parallel_execution() -> None:
    """Rule Engine and STL Detection run in parallel, both appear in completed steps."""
    async with (
        await WorkflowEnvironment.start_time_skipping() as env,
        Worker(
            env.client,
            task_queue="test-queue",
            workflows=[AnalysisPipelineWorkflow],
            activities=ALL_ACTIVITIES,
        ),
    ):
        handle = await env.client.start_workflow(
            AnalysisPipelineWorkflow.run,
            AnalysisPipelineInput(
                tenant_id="t-1",
                building_id="b-1",
                correlation_id="c-1",
            ),
            id="test-pipeline-parallel",
            task_queue="test-queue",
        )

        import asyncio

        for _ in range(100):
            status = await handle.query(AnalysisPipelineWorkflow.get_status)
            if status.is_waiting_for_human_review:
                break
            await asyncio.sleep(0.1)

        # Both parallel activities should have completed
        assert "rule_engine" in status.steps_completed
        assert "stl_detection" in status.steps_completed

        # They should appear after data_quality_gate
        idx_gate = status.steps_completed.index("data_quality_gate")
        idx_rule = status.steps_completed.index("rule_engine")
        idx_stl = status.steps_completed.index("stl_detection")
        assert idx_rule > idx_gate
        assert idx_stl > idx_gate

        # Complete the workflow
        await handle.signal(
            AnalysisPipelineWorkflow.human_review_completed,
            HumanReviewSignal(reviewer_id="r", action="approved"),
        )
        await handle.result()
