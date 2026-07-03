from __future__ import annotations

import os
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from temporalio import activity

from orchestration.temporal.dto import ActivityResult, DriftDetectionInput
from services.drift_detection.config import DriftDetectionConfig
from services.drift_detection.detector import detect_drift
from services.drift_detection.event_publisher import KafkaDriftEventPublisher
from services.drift_detection.models import DriftEventPayload, DriftStatus
from services.drift_detection.repository import DatabaseDriftRepository
from shared.auth.tenant_context import tenant_scope

# ---------------------------------------------------------------------------
# Minimal session factory — Integration dependency boundary.
#
# No global async engine exists on this branch (ENG-5 / API layer not yet
# merged). This adapter follows the repository-established convention of
# reading APP_DATABASE_URL from the environment (see conftest.py, env.py).
#
# FUTURE MERGE NOTE: Replace _get_session_factory() with the global async
# engine / session factory once the worker infrastructure from ENG-5 is
# merged into this branch. The calling code in drift_detection_activity
# requires no changes — only this factory function needs to be swapped.
# ---------------------------------------------------------------------------

_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the module-level async session factory, creating it once on first call.

    Reads APP_DATABASE_URL from the environment, which is the same variable
    the repository's integration test fixtures (conftest.py) and migration
    tooling (env.py) rely upon for the app-role connection.
    """
    global _session_factory
    if _session_factory is None:
        db_url = os.environ.get(
            "APP_DATABASE_URL",
            "postgresql+asyncpg://carbonsense_app:changeme@localhost:5432/carbonsense",
        )
        engine = create_async_engine(db_url, pool_pre_ping=True)
        _session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return _session_factory


@activity.defn
async def drift_detection_activity(input: DriftDetectionInput) -> ActivityResult:
    """Temporal activity: evaluate building-level drift for one (tenant, building) pair.

    Execution path:
      1. Acquire an async DB session via the module-level session factory.
      2. Set RLS tenant context via tenant_scope.
      3. Fetch building metadata and trailing normalized_readings via DatabaseDriftRepository.
      4. Run the Mann-Kendall trend test via detect_drift.
      5. If drifting: publish model.drift.detected + customer notification.
      6. Return ActivityResult to the calling DriftDetectionWorkflow.
    """
    logger = structlog.get_logger(__name__).bind(
        tenant_id=input.tenant_id,
        building_id=input.building_id,
    )
    logger.info("Starting drift detection activity")

    tenant_uuid = UUID(input.tenant_id)
    building_uuid = UUID(input.building_id)

    config = DriftDetectionConfig()
    publisher = KafkaDriftEventPublisher()

    # 1. Fetch historical readings inside a tenant-scoped database session.
    factory = _get_session_factory()
    async with factory() as session:
        async with tenant_scope(session, tenant_uuid) as scoped_session:
            repo = DatabaseDriftRepository(scoped_session)
            building_type, climate_zone = await repo.get_building_context(building_uuid)
            readings = await repo.get_trailing_readings(tenant_uuid, building_uuid, days=30)

    # 2. Run drift detection business logic (pure function, no I/O).
    drift_result = detect_drift(
        tenant_id=tenant_uuid,
        building_id=building_uuid,
        readings=readings,
        config=config,
        building_type=building_type,
        climate_zone=climate_zone,
    )

    # 3. Handle results — publish events only when drifting.
    if drift_result.status == DriftStatus.DRIFTING:
        logger.info(
            "Drift detected, publishing events",
            trend=drift_result.trend_direction.value,
            magnitude=drift_result.magnitude,
        )
        payload = DriftEventPayload(
            tenant_id=tenant_uuid,
            building_id=building_uuid,
            trend_direction=drift_result.trend_direction,
            magnitude=drift_result.magnitude,
            timestamp=drift_result.evaluated_at,
        )
        publisher.publish_drift_detected(payload)
        publisher.publish_customer_notification(str(tenant_uuid), str(building_uuid))

        return ActivityResult(
            step_name="drift_detection",
            status="completed",
            detail=f"Drift detected: {drift_result.trend_direction.value}",
        )

    logger.info("Drift detection evaluated as stable", status=drift_result.status.value)
    return ActivityResult(
        step_name="drift_detection",
        status="completed",
        detail=f"Status: {drift_result.status.value}",
    )
