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
from pipelines.dataset_ingestion.ingest import ingest_public_dataset
from pipelines.feature_engineering.batch_pipeline import run_batch_feature_engineering
from pipelines.training.train_and_evaluate import train_and_evaluate
from shared.auth.tenant_context import tenant_scope
from shared.database import get_session_factory

pytestmark = pytest.mark.e2e

_MLFLOW_TRACKING_URI_TEMPLATE = "sqlite:///{path}/mlflow.db"
_BDG2_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "datasets" / "bdg2_sample.csv"
_BDG2_WINDOW_START = datetime.datetime(2016, 1, 1, tzinfo=datetime.UTC)
_BDG2_WINDOW_END = datetime.datetime(2016, 4, 29, 10, tzinfo=datetime.UTC)


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


@pytest_asyncio.fixture()
async def onboarded_building() -> AsyncIterator[tuple[uuid.UUID, uuid.UUID]]:
    """Tenant + building + a calendar spanning the real BDG2 fixture's date
    range -- unlike seeded_building, circuits and readings are deliberately
    NOT pre-seeded here. They're created by ingest_public_dataset() itself,
    so this fixture proves the complete real chain starting from Dataset
    Ingestion (Dataset -> Ingestion -> Cleaning -> Canonical Schema ->
    Feature Engineering -> Training -> Evaluation -> Model Versioning),
    rather than bypassing ingestion the way seeded_building's direct SQL
    inserts do."""
    tenant_id, building_id = uuid.uuid4(), uuid.uuid4()
    factory = get_session_factory()

    async with factory() as session, tenant_scope(session, tenant_id):
        await session.execute(
            text(
                "INSERT INTO tenants (tenant_id, name, isolation_tier) "
                "VALUES (:id, 'e2e-bdg2-tenant', 'shared_rls')"
            ),
            {"id": str(tenant_id)},
        )
        await session.execute(
            text(
                "INSERT INTO buildings (building_id, tenant_id, name, building_type, timezone) "
                "VALUES (:building_id, :tenant_id, 'e2e-bdg2-building', 'office', 'UTC')"
            ),
            {"building_id": str(building_id), "tenant_id": str(tenant_id)},
        )

        day = _BDG2_WINDOW_START.date()
        end = _BDG2_WINDOW_END.date()
        while day <= end:
            day_type = "weekend" if day.weekday() >= 5 else "business_day"
            await session.execute(
                text(
                    "INSERT INTO building_calendar (tenant_id, building_id, date, day_type) "
                    "VALUES (:tenant_id, :building_id, :date, :day_type)"
                ),
                {
                    "tenant_id": str(tenant_id),
                    "building_id": str(building_id),
                    "date": day,
                    "day_type": day_type,
                },
            )
            day += datetime.timedelta(days=1)
        await session.commit()

    yield tenant_id, building_id

    async with factory() as session, tenant_scope(session, tenant_id):
        for table in (
            "feature_store",
            "findings",
            "normalized_readings",
            "ingestion_batches",
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
async def test_real_bdg2_dataset_flows_through_complete_pipeline(
    onboarded_building: tuple[uuid.UUID, uuid.UUID], tmp_path: Path
) -> None:
    """Real BDG2 data (tests/fixtures/datasets/bdg2_sample.csv -- see that
    directory's README for exact provenance) flows through every stage of
    the pipeline via its real entry points, not a synthetic shortcut:
    Dataset -> Ingestion (ingest_public_dataset) -> Cleaning (the same
    DataQualityGate CSV upload uses) -> Canonical Schema
    (normalized_readings) -> Feature Engineering
    (run_batch_feature_engineering) -> Training -> Evaluation -> Model
    Versioning (train_and_evaluate)."""
    tenant_id, building_id = onboarded_building

    ingestion_summary = await ingest_public_dataset(
        file_path=_BDG2_FIXTURE,
        source_id="bdg2",
        tenant_id=tenant_id,
        building_id=building_id,
    )
    assert ingestion_summary.total_rows == 8598
    assert ingestion_summary.pass_count > 0
    assert ingestion_summary.quarantined_count == 0

    features = await run_batch_feature_engineering(
        tenant_id, building_id, _BDG2_WINDOW_START, _BDG2_WINDOW_END
    )
    assert len(features) > 0

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
    for outcome in summary.outcomes:
        assert outcome.result.registered_version is not None
        assert outcome.result.n_training_samples > 0


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
