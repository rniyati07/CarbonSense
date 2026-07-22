"""ENG-6d — calendar-cadence retraining + post-promotion rollback
monitoring schedule bootstrap.

orchestration/temporal/schedules/retraining.py's register_retraining_schedule()
(the first of TRD v2.0 §6.2's three triggers) has existed since before
ENG-6 but was never called from anywhere -- no building ever actually got
a monthly retraining schedule. This script is that missing wiring: iterate
every tenant's buildings and register one, plus the companion daily
rollback-monitoring schedule (TRD v2.0 §6.4), idempotently (Temporal's own
ScheduleAlreadyRunningError is caught and skipped, not treated as a
failure -- this script is meant to be re-run safely, e.g. after onboarding
a new building, without re-registering existing schedules).

Usage:
    python scripts/bootstrap/register_retraining_schedules.py
"""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from sqlalchemy import text
from temporalio.client import Client, ScheduleAlreadyRunningError

from apps.worker.config import build_tls_config
from services.tenant_admin.repository import TenantAdminRepository
from shared.auth.tenant_context import tenant_scope
from shared.config.temporal import TemporalSettings
from shared.database import get_session_factory

logger = logging.getLogger(__name__)


async def _list_all_tenant_ids() -> list[UUID]:
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(text("SELECT tenant_id FROM tenants"))
        return [row.tenant_id for row in result.fetchall()]


async def register_all() -> tuple[int, int]:
    from orchestration.temporal.schedules.retraining import register_retraining_schedule
    from orchestration.temporal.schedules.rollback_monitoring import (
        register_rollback_monitoring_schedule,
    )

    settings = TemporalSettings()
    client = await Client.connect(
        settings.host, namespace=settings.namespace, tls=build_tls_config(settings)
    )

    registered = 0
    skipped = 0
    factory = get_session_factory()

    for tenant_id in await _list_all_tenant_ids():
        async with factory() as session, tenant_scope(session, tenant_id):
            buildings = await TenantAdminRepository(session).list_buildings(tenant_id)

        for building in buildings:
            for label, register in (
                ("retraining", register_retraining_schedule),
                ("rollback-monitoring", register_rollback_monitoring_schedule),
            ):
                try:
                    await register(
                        client,
                        task_queue=settings.task_queue,
                        tenant_id=str(tenant_id),
                        building_id=str(building.building_id),
                    )
                    registered += 1
                    print(  # noqa: T201
                        f"Registered {label} schedule: tenant={tenant_id} "
                        f"building={building.building_id}"
                    )
                except ScheduleAlreadyRunningError:
                    skipped += 1

    return registered, skipped


def main() -> None:
    registered, skipped = asyncio.run(register_all())
    print(f"Done: {registered} schedules registered, {skipped} already existed.")  # noqa: T201


if __name__ == "__main__":
    main()
