"""ENG-6e — full AI training pipeline, end to end against a live
TimescaleDB: real readings -> Feature Assembly (persisting to
feature_store, ENG-6 Phase 0) -> pipelines.training.train_and_evaluate()
(fetch from feature_store -> train Isolation Forest + Autoencoder ->
promotion gate -> promote) -> verify a real, loadable model is registered.

Mirrors test_analysis_pipeline_e2e.py's exact conventions (same seeded-
building fixture shape, same CI exclusion rationale -- marked `e2e`, not
`integration`, since the `test-integration` CI job runs with no database
service; see that file's module docstring for the full explanation of why
this is real, correct, locally-runnable test infrastructure that isn't
wired into CI's `-m integration` selection).

Requires:
    - A running TimescaleDB with migrations 0001-0009 applied.
    - APP_DATABASE_URL environment variable set (see
      test_analysis_pipeline_e2e.py for the exact default).
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text

from orchestration.temporal.activities.analysis_stubs import (
    feature_assembly_activity,
    rule_engine_activity,
    stl_detection_activity,
)
from orchestration.temporal.dto import AnalysisPipelineInput
from pipelines.training.train_and_evaluate import train_and_evaluate
from shared.auth.tenant_context import tenant_scope
from shared.database import get_session_factory

pytestmark = pytest.mark.e2e

_MLFLOW_TRACKING_URI_TEMPLATE = "sqlite:///{path}/mlflow.db"


@pytest_asyncio.fixture()
async def seeded_building() -> AsyncIterator[tuple[uuid.UUID, uuid.UUID]]:
    """30 days of clean sinusoidal-ish hourly readings -- enough real
    history for both trainers' "at least 2 usable feature rows"
    requirement to be trivially satisfied, and enough for the Autoencoder
    to form at least one full 24h window."""
    tenant_id, building_id, circuit_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    today = datetime.date.today()
    factory = get_session_factory()

    async with factory() as session, tenant_scope(session, tenant_id):
        await session.execute(
            text(
                "INSERT INTO tenants (tenant_id, name, isolation_tier) "
                "VALUES (:id, 'e2e-training-tenant', 'shared_rls')"
            ),
            {"id": str(tenant_id)},
        )
        await session.execute(
            text(
                "INSERT INTO buildings (building_id, tenant_id, name, building_type, timezone) "
                "VALUES (:building_id, :tenant_id, 'e2e-training-building', 'office', 'UTC')"
            ),
            {"building_id": str(building_id), "tenant_id": str(tenant_id)},
        )
        await session.execute(
            text(
                "INSERT INTO submeter_circuits (circuit_id, tenant_id, building_id, circuit_type) "
                "VALUES (:circuit_id, :tenant_id, :building_id, 'hvac')"
            ),
            {
                "circuit_id": str(circuit_id),
                "tenant_id": str(tenant_id),
                "building_id": str(building_id),
            },
        )

        for day_offset in range(30, 0, -1):
            day = today - datetime.timedelta(days=day_offset)
            await session.execute(
                text(
                    "INSERT INTO building_calendar (tenant_id, building_id, date, day_type) "
                    "VALUES (:tenant_id, :building_id, :date, 'business_day')"
                ),
                {"tenant_id": str(tenant_id), "building_id": str(building_id), "date": day},
            )
            for hour in range(24):
                ts = datetime.datetime.combine(day, datetime.time(hour, 0), tzinfo=datetime.UTC)
                kwh = 10.0 + 4.0 * (1 if 8 <= hour <= 18 else -1)
                await session.execute(
                    text(
                        "INSERT INTO normalized_readings "
                        "(tenant_id, circuit_id, ts, kwh, data_quality_status) "
                        "VALUES (:tenant_id, :circuit_id, :ts, :kwh, 'pass')"
                    ),
                    {
                        "tenant_id": str(tenant_id),
                        "circuit_id": str(circuit_id),
                        "ts": ts,
                        "kwh": kwh,
                    },
                )
        await session.commit()

    yield tenant_id, building_id

    async with factory() as session, tenant_scope(session, tenant_id):
        for table in (
            "feature_store",
            "findings",
            "normalized_readings",
            "building_calendar",
            "submeter_circuits",
            "buildings",
            "tenants",
        ):
            await session.execute(
                text(f"DELETE FROM {table} WHERE tenant_id = :tid"),  # noqa: S608
                {"tid": str(tenant_id)},
            )
        await session.commit()


@pytest.mark.asyncio
async def test_full_training_pipeline_registers_a_promotable_model(
    seeded_building: tuple[uuid.UUID, uuid.UUID], tmp_path: Path
) -> None:
    tenant_id, building_id = seeded_building
    input = AnalysisPipelineInput(
        tenant_id=str(tenant_id), building_id=str(building_id), correlation_id="e2e-training"
    )

    # Populate the feature store the same way a real AnalysisPipelineWorkflow
    # run does (Rule Engine + STL -> Feature Assembly, ENG-6 Phase 0's
    # persistence addition) -- not a separate/parallel code path.
    rule_output = await rule_engine_activity(input)
    stl_output = await stl_detection_activity(input)
    feature_output = await feature_assembly_activity(input, rule_output, stl_output)
    assert len(feature_output.features) > 0

    tracking_uri = _MLFLOW_TRACKING_URI_TEMPLATE.format(path=tmp_path)
    summary = await train_and_evaluate(
        tenant_id=tenant_id,
        building_id=building_id,
        building_type="office",
        trigger="calendar",
        mlflow_tracking_uri=tracking_uri,
    )

    assert summary.skipped_reason is None
    assert len(summary.outcomes) == 2
    model_types = {o.result.model_type for o in summary.outcomes}
    assert model_types == {"isolation_forest", "autoencoder"}
    for outcome in summary.outcomes:
        assert outcome.result.registered_version is not None
        assert outcome.result.n_training_samples > 0
