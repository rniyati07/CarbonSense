"""ENG-6d — RollbackMonitoringWorkflow (TRD v2.0 §6.4): scheduled cron
workflow, one execution per building, checking both ensemble members'
post-promotion false-positive rate and rolling back automatically if
either has regressed beyond the configured ceiling. Mirrors
DriftDetectionWorkflow's shape (a scheduled check outside the real-time
Analysis Pipeline) but fans out to two activities, one per model_type,
since Isolation Forest and the Autoencoder are independently promoted and
can independently regress.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from orchestration.temporal.activities.rollback_check import rollback_check_activity
    from orchestration.temporal.dto import (
        ActivityResult,
        RollbackCheckInput,
        RollbackMonitoringInput,
    )


@workflow.defn
class RollbackMonitoringWorkflow:
    @workflow.run
    async def run(self, input: RollbackMonitoringInput) -> list[ActivityResult]:
        if not input.tenant_id or not input.building_id:
            raise ApplicationError("tenant_id and building_id are required", non_retryable=True)

        results: list[ActivityResult] = []
        for model_type in ("isolation_forest", "autoencoder"):
            result = await workflow.execute_activity(
                rollback_check_activity,
                RollbackCheckInput(
                    tenant_id=input.tenant_id,
                    building_id=input.building_id,
                    model_type=model_type,
                    window_days=input.window_days,
                ),
                start_to_close_timeout=timedelta(minutes=5),
                heartbeat_timeout=timedelta(seconds=30),
            )
            results.append(result)
        return results
