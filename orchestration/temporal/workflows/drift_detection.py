from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from orchestration.temporal.activities.drift_detection_stub import (
        drift_detection_activity,
    )
    from orchestration.temporal.dto import ActivityResult, DriftDetectionInput


@workflow.defn
class DriftDetectionWorkflow:
    """Scheduled nightly per building (TRD v2.0 section 3.5).

    Explicitly out of the real-time request path. Drift is a slow-moving
    signal; computing it on every request would be wasted work.
    """

    @workflow.run
    async def run(self, input: DriftDetectionInput) -> ActivityResult:
        if not input.tenant_id:
            raise ApplicationError("tenant_id is required", non_retryable=True)
        return await workflow.execute_activity(
            drift_detection_activity,
            input,
            start_to_close_timeout=timedelta(minutes=30),
        )
