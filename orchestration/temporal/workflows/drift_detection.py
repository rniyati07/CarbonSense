from __future__ import annotations

from datetime import timedelta

from temporalio import workflow

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
        if not input.tenant_id or not input.building_id:
            raise ValueError("tenant_id and building_id are required")

        result = await workflow.execute_activity(
            drift_detection_activity,
            input,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=None, # Configure retries explicitly as needed
        )
        
        return result
