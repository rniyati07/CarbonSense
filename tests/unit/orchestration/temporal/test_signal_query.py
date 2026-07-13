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

from orchestration.temporal.dto import (
    AnalysisPipelineInput,
    ConfidenceCalibrationOutput,
    DataQualityGateOutput,
    ExplainabilityOutput,
    FeatureAssemblyOutput,
    HumanReviewSignal,
    MLEnsembleOutput,
    RuleEngineOutput,
    STLOutput,
)
from orchestration.temporal.workflows.analysis_pipeline import AnalysisPipelineWorkflow


# CONFIRMED BUG (pre-ENG-4 integration audit), still the governing reason
# every activity below is mocked rather than imported real -- see the full
# explanation in test_analysis_pipeline.py. Every mock is registered under
# its real activity's name and matches that real activity's CURRENT
# (input, ...) signature and return type exactly, since the ENG-2c-wiring
# Phase 9 commit rewired analysis_pipeline.py to thread every activity's
# real output into the next.
@activity.defn(name="data_quality_gate_activity")
async def mocked_data_quality_gate_activity(
    input: AnalysisPipelineInput,
) -> DataQualityGateOutput:
    return DataQualityGateOutput(overall_status="pass", pass_count=1)


@activity.defn(name="rule_engine_activity")
async def mocked_rule_engine_activity(input: AnalysisPipelineInput) -> RuleEngineOutput:
    return RuleEngineOutput(findings=[], rule_fires=[])


@activity.defn(name="stl_detection_activity")
async def mocked_stl_detection_activity(input: AnalysisPipelineInput) -> STLOutput:
    return STLOutput(residuals=[])


@activity.defn(name="feature_assembly_activity")
async def mocked_feature_assembly_activity(
    input: AnalysisPipelineInput,
    rule_output: RuleEngineOutput,
    stl_output: STLOutput,
) -> FeatureAssemblyOutput:
    return FeatureAssemblyOutput(features=[])


@activity.defn(name="ml_ensemble_activity")
async def mocked_ml_ensemble_activity(
    input: AnalysisPipelineInput,
    feature_output: FeatureAssemblyOutput,
) -> MLEnsembleOutput:
    return MLEnsembleOutput(scores=[])


@activity.defn(name="confidence_calibration_activity")
async def mocked_confidence_calibration_activity(
    input: AnalysisPipelineInput,
    ml_output: MLEnsembleOutput,
) -> ConfidenceCalibrationOutput:
    return ConfidenceCalibrationOutput(calibrated_scores=[])


@activity.defn(name="root_cause_attribution_activity")
async def mocked_root_cause_attribution_activity(
    input: AnalysisPipelineInput,
    feature_output: FeatureAssemblyOutput,
    calibration_output: ConfidenceCalibrationOutput,
) -> ExplainabilityOutput:
    return ExplainabilityOutput(persisted_finding_ids=[], bundles=[])


ALL_ACTIVITIES = [
    mocked_data_quality_gate_activity,
    mocked_rule_engine_activity,
    mocked_stl_detection_activity,
    mocked_feature_assembly_activity,
    mocked_ml_ensemble_activity,
    mocked_confidence_calibration_activity,
    mocked_root_cause_attribution_activity,
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
