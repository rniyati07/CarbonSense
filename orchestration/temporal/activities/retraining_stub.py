from __future__ import annotations

from temporalio import activity

from orchestration.temporal.dto import ActivityResult, RetrainingInput


@activity.defn
async def retraining_activity(input: RetrainingInput) -> ActivityResult:
    # TODO(ENG-6): Per-tenant/per-building model retraining via MLflow
    return ActivityResult(
        step_name="retraining",
        status="completed",
        detail=(
            f"TODO(ENG-6): stub for tenant={input.tenant_id} "
            f"building={input.building_id} trigger={input.trigger}"
        ),
    )
