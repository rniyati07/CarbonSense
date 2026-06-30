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
    threshold crossing. The retraining workflow is parameterized with tenant_id
    so the training-data query runs through RLS-enforced connections.
    """

    @workflow.run
    async def run(self, input: RetrainingInput) -> ActivityResult:
        if not input.tenant_id:
            raise ApplicationError("tenant_id is required", non_retryable=True)
        return await workflow.execute_activity(
            retraining_activity,
            input,
            start_to_close_timeout=timedelta(minutes=60),
        )
