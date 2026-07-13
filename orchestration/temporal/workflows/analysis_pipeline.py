from __future__ import annotations

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
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
        AnalysisPipelineStatus,
        HumanReviewSignal,
    )


@workflow.defn
class AnalysisPipelineWorkflow:
    """Orchestrates the 7-layer anomaly detection pipeline + human review.

    Execution graph:
        Data Quality Gate
        -> (Rule Engine || STL Detection)  [parallel]
        -> Feature Assembly
        -> ML Ensemble
        -> Confidence Calibration
        -> Root Cause Attribution
        -> Human Review Wait  [Temporal Signal]
        -> Complete
    """

    def __init__(self) -> None:
        self._current_step: str = "not_started"
        self._steps_completed: list[str] = []
        self._waiting_for_human_review: bool = False
        self._human_review_signal: HumanReviewSignal | None = None

    @workflow.run
    async def run(self, input: AnalysisPipelineInput) -> str:
        if not input.tenant_id:
            raise ApplicationError("tenant_id is required", non_retryable=True)

        # Layer 1: Data Quality Gate -- lightweight verification against
        # already-persisted normalized data (see services/ingestion/
        # repository.py). Raises non-retryable if the window has no
        # pass/degraded data at all; result isn't needed downstream.
        self._current_step = "data_quality_gate"
        await workflow.execute_activity(
            data_quality_gate_activity,
            input,
            start_to_close_timeout=timedelta(minutes=5),
        )
        self._steps_completed.append("data_quality_gate")

        # Layer 2+3: Rule Engine || STL Detection (parallel). Both outputs
        # are threaded forward as DTOs -- rule fires and STL residual
        # fields are never persisted (see orchestration/temporal/dto.py's
        # architecture-decision note), so this is the only place they can
        # still be read once produced.
        self._current_step = "rule_engine_and_stl_detection"
        rule_task = workflow.execute_activity(
            rule_engine_activity,
            input,
            start_to_close_timeout=timedelta(minutes=5),
        )
        stl_task = workflow.execute_activity(
            stl_detection_activity,
            input,
            start_to_close_timeout=timedelta(minutes=5),
        )
        rule_output, stl_output = await asyncio.gather(rule_task, stl_task)
        self._steps_completed.append("rule_engine")
        self._steps_completed.append("stl_detection")

        # Feature Assembly (feature_set_v1)
        self._current_step = "feature_assembly"
        feature_output = await workflow.execute_activity(
            feature_assembly_activity,
            args=[input, rule_output, stl_output],
            start_to_close_timeout=timedelta(minutes=5),
        )
        self._steps_completed.append("feature_assembly")

        # Layer 4: ML Ensemble
        self._current_step = "ml_ensemble"
        ml_output = await workflow.execute_activity(
            ml_ensemble_activity,
            args=[input, feature_output],
            start_to_close_timeout=timedelta(minutes=10),
        )
        self._steps_completed.append("ml_ensemble")

        # Layer 6: Confidence Calibration
        self._current_step = "confidence_calibration"
        calibration_output = await workflow.execute_activity(
            confidence_calibration_activity,
            args=[input, ml_output],
            start_to_close_timeout=timedelta(minutes=5),
        )
        self._steps_completed.append("confidence_calibration")

        # Layer 7: Root Cause Attribution
        self._current_step = "root_cause_attribution"
        await workflow.execute_activity(
            root_cause_attribution_activity,
            args=[input, feature_output, calibration_output],
            start_to_close_timeout=timedelta(minutes=5),
        )
        self._steps_completed.append("root_cause_attribution")

        # Human Review Wait (signal-based, NOT sleep/polling)
        self._current_step = "waiting_for_human_review"
        self._waiting_for_human_review = True
        await workflow.wait_condition(lambda: self._human_review_signal is not None)
        self._waiting_for_human_review = False
        self._steps_completed.append("human_review")

        self._current_step = "completed"
        return f"Pipeline completed for building {input.building_id}"

    @workflow.signal
    async def human_review_completed(self, signal: HumanReviewSignal) -> None:
        self._human_review_signal = signal

    @workflow.query
    def get_status(self) -> AnalysisPipelineStatus:
        return AnalysisPipelineStatus(
            workflow_id=workflow.info().workflow_id,
            current_step=self._current_step,
            steps_completed=list(self._steps_completed),
            is_waiting_for_human_review=self._waiting_for_human_review,
        )
