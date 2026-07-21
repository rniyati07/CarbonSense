from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from orchestration.temporal.activities.retraining_stub import retraining_activity
    from orchestration.temporal.dto import ActivityResult, RetrainingInput


@workflow.defn
class RetrainingWorkflow:
    """Per-tenant/per-building model retraining (TRD v2.0 section 3.8, section 6).

    Three triggers: calendar cadence, drift detection event, feedback-volume
    threshold crossing (ENG-6d wires all three -- see
    orchestration/events/kafka/drift_retraining_trigger.py,
    orchestration/events/kafka/feedback_retraining_trigger.py, and
    orchestration/temporal/schedules/retraining.py). The retraining workflow
    is parameterized with tenant_id so the training-data query runs through
    RLS-enforced connections.

    120-minute timeout (not MLEnsembleTrainingWorkflow's per-model 60
    minutes): retraining_activity trains both Isolation Forest and the
    Autoencoder sequentially within one activity call (ENG-6d reuses
    pipelines.training.train_and_evaluate() rather than duplicating that
    per-model split as two activities here).
    """

    @workflow.run
    async def run(self, input: RetrainingInput) -> ActivityResult:
        if not input.tenant_id or not input.building_id:
            raise ApplicationError("tenant_id and building_id are required", non_retryable=True)
        return await workflow.execute_activity(
            retraining_activity,
            input,
            start_to_close_timeout=timedelta(minutes=120),
            heartbeat_timeout=timedelta(seconds=30),
        )
