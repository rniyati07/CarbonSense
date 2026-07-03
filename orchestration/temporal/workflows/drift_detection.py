from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from orchestration.temporal.activities.drift_detection_stub import (
        drift_detection_activity,
    )
    from orchestration.temporal.dto import (
        ActivityResult,
        DriftDetectionInput,
    )


@workflow.defn
class DriftDetectionWorkflow:
    """Scheduled cron workflow for building-level drift detection.
    
    Runs entirely outside the real-time Analysis Pipeline.
    Calculates drift over a trailing window and publishes events if drift is found.
    """

    @workflow.run
    async def run(self, input: DriftDetectionInput) -> ActivityResult:
        # Merge conflict resolution (pre-ENG-4 integration audit): develop's
        # side (from the eng-3g-originated fix, a717ad3/6157923) validated
        # only tenant_id but used the correct non-retryable ApplicationError
        # -- a plain ValueError here is treated as retryable by the Temporal
        # Python SDK and made input-validation-failure tests hang waiting for
        # a WorkflowFailureError that never arrived. eng-3e's side added the
        # building_id check but reverted to the plain ValueError that caused
        # exactly that hang. Combined: both required fields, non-retryable.
        if not input.tenant_id or not input.building_id:
            raise ApplicationError(
                "tenant_id and building_id are required", non_retryable=True
            )

        result = await workflow.execute_activity(
            drift_detection_activity,
            input,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=None,  # Configure retries explicitly as needed
        )

        return result
