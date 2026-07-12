"""ENG-2c: Signal and query handler tests.

Tests that:
- Workflow genuinely pauses waiting for signal (not sleep/polling)
- Signal resumes workflow execution
- Query returns accurate status without modifying state
"""

from __future__ import annotations

import asyncio

import pytest
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from orchestration.temporal.activities.analysis_stubs import (
    feature_assembly_activity,
    ml_ensemble_activity,
    root_cause_attribution_activity,
    rule_engine_activity,
    stl_detection_activity,
)
from orchestration.temporal.dto import (
    ActivityResult,
    AnalysisPipelineInput,
    DataQualityGateOutput,
    HumanReviewSignal,
)
from orchestration.temporal.workflows.analysis_pipeline import AnalysisPipelineWorkflow


# CONFIRMED BUG (pre-ENG-4 integration audit): see the identical fix and
# full explanation in test_analysis_pipeline.py -- confidence_calibration_activity
# stopped being a stub once ENG-3f merged, opens a real DB session, has no
# retry_policy on its workflow.execute_activity() call (Temporal retries
# indefinitely by default), and this test file was never updated after that
# merge. Hung both locally and in CI (test-unit ran 50+ minutes) until fixed.
@activity.defn(name="confidence_calibration_activity")
async def mocked_confidence_calibration_activity(
    input: AnalysisPipelineInput,
) -> ActivityResult:
    return ActivityResult(
        step_name="confidence_calibration",
        status="completed",
        detail=f"Mocked calibration for tenant={input.tenant_id}",
    )


# Same rationale, now also true of data_quality_gate_activity since the
# ENG-2c-wiring Phase 1 commit made it open a real DB session and parse
# tenant_id/building_id as UUIDs (see services/ingestion/repository.py).
@activity.defn(name="data_quality_gate_activity")
async def mocked_data_quality_gate_activity(
    input: AnalysisPipelineInput,
) -> DataQualityGateOutput:
    return DataQualityGateOutput(overall_status="pass", pass_count=1)


ALL_ACTIVITIES = [
    mocked_data_quality_gate_activity,
    rule_engine_activity,
    stl_detection_activity,
    feature_assembly_activity,
    ml_ensemble_activity,
    mocked_confidence_calibration_activity,
    root_cause_attribution_activity,
]

PIPELINE_INPUT = AnalysisPipelineInput(
    tenant_id="t-signal",
    building_id="b-signal",
    correlation_id="c-signal",
)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_query_returns_status_mid_execution() -> None:
    """Query handler returns accurate step information without modifying state."""
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
            PIPELINE_INPUT,
            id="test-query-status",
            task_queue="test-queue",
        )

        # Wait for human review point
        for _ in range(100):
            status = await handle.query(AnalysisPipelineWorkflow.get_status)
            if status.is_waiting_for_human_review:
                break
            await asyncio.sleep(0.1)

        # Query should reflect all 7 completed steps
        assert len(status.steps_completed) == 7
        assert status.current_step == "waiting_for_human_review"
        assert status.is_waiting_for_human_review is True

        # Query again — state should not change from querying
        status2 = await handle.query(AnalysisPipelineWorkflow.get_status)
        assert status2.steps_completed == status.steps_completed

        # Clean up
        await handle.signal(
            AnalysisPipelineWorkflow.human_review_completed,
            HumanReviewSignal(reviewer_id="r", action="approved"),
        )
        await handle.result()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_signal_resumes_paused_workflow() -> None:
    """Signal arrival causes a genuinely paused workflow to resume and complete."""
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
            PIPELINE_INPUT,
            id="test-signal-resume",
            task_queue="test-queue",
        )

        # Wait for the human review pause
        for _ in range(100):
            status = await handle.query(AnalysisPipelineWorkflow.get_status)
            if status.is_waiting_for_human_review:
                break
            await asyncio.sleep(0.1)
        assert status.is_waiting_for_human_review is True

        # Send signal
        await handle.signal(
            AnalysisPipelineWorkflow.human_review_completed,
            HumanReviewSignal(
                reviewer_id="user-42",
                action="approved",
                comment="LGTM",
            ),
        )

        # Workflow should complete
        result = await handle.result()
        assert "completed" in result.lower()

        # Query post-completion should show human_review in completed steps
        status = await handle.query(AnalysisPipelineWorkflow.get_status)
        assert "human_review" in status.steps_completed
        assert status.current_step == "completed"
        assert status.is_waiting_for_human_review is False
