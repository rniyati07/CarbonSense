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
# Mocked return type is ConfidenceCalibrationOutput, not the old
# ActivityResult, since the ENG-2c-wiring Phase 7 commit gave the real
# confidence_calibration_activity a (input, ml_output) signature and that
# return type -- see the FeatureAssemblyOutput mock below for why this
# must track the real function's annotation.
@activity.defn(name="confidence_calibration_activity")
async def mocked_confidence_calibration_activity(
    input: AnalysisPipelineInput,
) -> ConfidenceCalibrationOutput:
    return ConfidenceCalibrationOutput(calibrated_scores=[])


# Same rationale as above, now also true of data_quality_gate_activity since
# the ENG-2c-wiring Phase 1 commit (see services/ingestion/repository.py):
# it opens a real DB session and parses tenant_id/building_id as UUIDs, so
# this workflow-orchestration test must not depend on either a live database
# or on its fixture strings being valid UUIDs.
@activity.defn(name="data_quality_gate_activity")
async def mocked_data_quality_gate_activity(
    input: AnalysisPipelineInput,
) -> DataQualityGateOutput:
    return DataQualityGateOutput(overall_status="pass", pass_count=1)


# Same rationale, now also true of rule_engine_activity and
# stl_detection_activity since the ENG-2c-wiring Phase 4 commit made both
# open real DB sessions and parse tenant_id/building_id as UUIDs (see
# services/rules_engine/repository.py, services/stl_detection/repository.py).
@activity.defn(name="rule_engine_activity")
async def mocked_rule_engine_activity(input: AnalysisPipelineInput) -> RuleEngineOutput:
    return RuleEngineOutput(findings=[], rule_fires=[])


@activity.defn(name="stl_detection_activity")
async def mocked_stl_detection_activity(input: AnalysisPipelineInput) -> STLOutput:
    return STLOutput(residuals=[])


# Same rationale, now also true of feature_assembly_activity since the
# ENG-2c-wiring Phase 5 commit gave it a real (input, rule_output,
# stl_output) signature, a real DB session, and a FeatureAssemblyOutput
# return type -- the workflow itself still calls it with a single
# AnalysisPipelineInput arg until Phase 9 rewires the workflow's call
# sites to thread every activity's output into the next, so this mock
# keeps the OLD single-arg contract the still-unmodified workflow
# actually invokes. The return type MUST still be FeatureAssemblyOutput,
# not the old ActivityResult -- workflow.execute_activity(...) resolves
# its expected return type from the real (unmocked) feature_assembly_activity
# function reference workflow.py imports directly, independent of which
# activity implementation the worker actually routes to by name; a mismatch
# here fails payload decoding on the workflow side (learned the hard way:
# an ActivityResult-returning mock crashed with "Failed decoding arguments").
@activity.defn(name="feature_assembly_activity")
async def mocked_feature_assembly_activity(input: AnalysisPipelineInput) -> FeatureAssemblyOutput:
    return FeatureAssemblyOutput(features=[])


# Same rationale, now also true of ml_ensemble_activity since the
# ENG-2c-wiring Phase 6 commit gave it a real (input, feature_output)
# signature and an MLEnsembleOutput return type.
@activity.defn(name="ml_ensemble_activity")
async def mocked_ml_ensemble_activity(input: AnalysisPipelineInput) -> MLEnsembleOutput:
    return MLEnsembleOutput(scores=[])


# Same rationale, now also true of root_cause_attribution_activity since the
# ENG-2c-wiring Phase 8 commit gave it a real
# (input, feature_output, calibration_output) signature and an
# ExplainabilityOutput return type.
@activity.defn(name="root_cause_attribution_activity")
async def mocked_root_cause_attribution_activity(
    input: AnalysisPipelineInput,
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
