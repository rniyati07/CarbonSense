"""ENG-2c: Analysis pipeline workflow tests.

DoD: End-to-end execution using stub activities, tenant_id validation,
and human signal received causing workflow resume and completion.
"""

from __future__ import annotations

import pytest
from temporalio.client import WorkflowFailureError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from orchestration.temporal.activities.analysis_stubs import (
    confidence_calibration_activity,
    data_quality_gate_activity,
    feature_assembly_activity,
    ml_ensemble_activity,
    root_cause_attribution_activity,
    rule_engine_activity,
    stl_detection_activity,
)
from orchestration.temporal.dto import (
    AnalysisPipelineInput,
    HumanReviewSignal,
)
from orchestration.temporal.workflows.analysis_pipeline import AnalysisPipelineWorkflow

ALL_ACTIVITIES = [
    data_quality_gate_activity,
    rule_engine_activity,
    stl_detection_activity,
    feature_assembly_activity,
    ml_ensemble_activity,
    confidence_calibration_activity,
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
