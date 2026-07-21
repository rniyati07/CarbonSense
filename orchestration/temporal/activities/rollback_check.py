"""ENG-6d — Temporal activity wrapping RollbackMonitor (TRD v2.0 §6.4).

The one Temporal-context adapter this needs: open a tenant-scoped
session, run the real check-and-rollback logic (models/evaluation/rollback.py),
commit. No rollback decision logic lives here.
"""

from __future__ import annotations

import datetime
import logging
from uuid import UUID

from temporalio import activity

from orchestration.temporal.dto import ActivityResult, RollbackCheckInput

logger = logging.getLogger(__name__)


@activity.defn
async def rollback_check_activity(input: RollbackCheckInput) -> ActivityResult:
    from models.evaluation.rollback import RollbackMonitor
    from models.registry.mlflow_registry import MLflowModelRegistry
    from shared.auth.tenant_context import tenant_scope
    from shared.database import get_session_factory

    activity.heartbeat()

    tenant_id = UUID(input.tenant_id)
    building_id = UUID(input.building_id)

    window_end = datetime.datetime.now(datetime.UTC)
    window_start = window_end - datetime.timedelta(days=input.window_days)

    monitor = RollbackMonitor(MLflowModelRegistry())

    factory = get_session_factory()
    async with factory() as session, tenant_scope(session, tenant_id):
        decision = await monitor.check_and_rollback(
            session, tenant_id, building_id, input.model_type, window_start, window_end
        )
        await session.commit()

    logger.info(
        "rollback_check_activity: tenant=%s building=%s model_type=%s rolled_back=%s -- %s",
        tenant_id,
        building_id,
        input.model_type,
        decision.rolled_back,
        decision.reason,
    )

    # status="completed" reflects that the check itself ran successfully --
    # decision.rolled_back (folded into detail) is what conveys whether it
    # took action, not whether the activity executed.
    return ActivityResult(
        step_name="rollback_check",
        status="completed",
        detail=f"rolled_back={decision.rolled_back}: {decision.reason}",
    )
