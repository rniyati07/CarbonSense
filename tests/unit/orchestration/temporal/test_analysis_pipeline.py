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
# every activity below is mocked rather than imported real: several of
# these activities open a real SQLAlchemy session against a live database
# or (Phase 6/8) load a real trained model from LocalModelRegistry. With
# neither reachable in this test environment and no retry_policy set on
# any workflow.execute_activity() call (Temporal retries indefinitely by
# default), a real activity here would hang both locally and in CI.
#
# ENG-2c's own documented DoD for this workflow is "runs end-to-end... with
# stubbed layer calls" -- this test exists to verify orchestration
# (sequencing, parallel execution, DTO threading, signal/human-review-wait),
# not any individual layer's business logic, which has its own coverage
# under tests/unit/services/. Every mock below is registered under its
# real activity's name (so workflow.execute_activity(...) routes to it) and
# matches that real activity's CURRENT (input, ...) signature and return
# type exactly -- the ENG-2c-wiring Phase 9 commit rewired
# analysis_pipeline.py itself to thread every activity's real output into
# the next, so these signatures must track workflow.py's actual call sites.
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
