from __future__ import annotations

from temporalio import activity

from orchestration.temporal.dto import ActivityResult, DriftDetectionInput


@activity.defn
async def drift_detection_activity(input: DriftDetectionInput) -> ActivityResult:
    # TODO(ENG-3e): Mann-Kendall trend test on rolling efficiency ratio
    return ActivityResult(
        step_name="drift_detection",
        status="completed",
        detail=f"TODO(ENG-3e): stub for tenant={input.tenant_id} building={input.building_id}",
    )
