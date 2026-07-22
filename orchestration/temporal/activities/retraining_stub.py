"""ENG-6d — Retraining activity: real implementation.

Filename kept as retraining_stub.py -- this codebase's established
convention is to fill in a "_stub" module with real logic rather than
rename it (see orchestration/temporal/activities/drift_detection_stub.py,
already a complete implementation despite its name), since renaming would
touch every workflow file's import for no functional benefit.

Delegates to pipelines.training.train_and_evaluate() -- the same
fetch-features -> train IF+AE -> evaluate -> promote flow ENG-6c built,
callable outside Temporal too (a script, a test). No training or
evaluation logic lives here; this activity is only the Temporal-context
adapter (fetch building_type, call the pipeline, shape the result).
"""

from __future__ import annotations

import logging
from uuid import UUID

from temporalio import activity

from orchestration.temporal.dto import ActivityResult, RetrainingInput

logger = logging.getLogger(__name__)


@activity.defn
async def retraining_activity(input: RetrainingInput) -> ActivityResult:
    from pipelines.training.train_and_evaluate import train_and_evaluate
    from services.tenant_admin.repository import TenantAdminRepository
    from shared.auth.tenant_context import tenant_scope
    from shared.database import get_session_factory

    activity.heartbeat()

    tenant_id = UUID(input.tenant_id)
    building_id = UUID(input.building_id)

    factory = get_session_factory()
    async with factory() as session, tenant_scope(session, tenant_id):
        building = await TenantAdminRepository(session).get_building(tenant_id, building_id)

    if building is None:
        return ActivityResult(
            step_name="retraining",
            status="skipped",
            detail=f"Building {building_id} not found for tenant {tenant_id}.",
        )

    activity.heartbeat()

    summary = await train_and_evaluate(
        tenant_id=tenant_id,
        building_id=building_id,
        building_type=building.building_type,
        trigger=input.trigger,
    )

    if summary.skipped_reason is not None:
        return ActivityResult(
            step_name="retraining", status="skipped", detail=summary.skipped_reason
        )

    promoted = [o.result.model_type for o in summary.outcomes if o.decision.approved]
    held = [
        o.result.model_type
        for o in summary.outcomes
        if not o.decision.approved and o.decision.requires_human_review
    ]
    rejected = [
        o.result.model_type
        for o in summary.outcomes
        if not o.decision.approved and not o.decision.requires_human_review
    ]

    logger.info(
        "retraining_activity: tenant=%s building=%s trigger=%s promoted=%s held=%s rejected=%s",
        tenant_id,
        building_id,
        input.trigger,
        promoted,
        held,
        rejected,
    )

    return ActivityResult(
        step_name="retraining",
        status="completed",
        detail=(
            f"trigger={input.trigger} n_features={summary.n_features_used} "
            f"promoted={promoted or 'none'} held_for_review={held or 'none'} "
            f"rejected={rejected or 'none'}"
        ),
    )
