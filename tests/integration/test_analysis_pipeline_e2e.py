"""ENG-2c-wiring Phase 10 — full AnalysisPipelineWorkflow activity chain,
end to end against a live TimescaleDB.

Runs Raw Data -> Data Quality Gate -> Rule Engine -> STL Detection ->
Feature Assembly -> ML Ensemble -> Confidence Calibration -> Root-Cause
Attribution by calling each activity function directly in the same order
and with the same DTO threading orchestration/temporal/workflows/
analysis_pipeline.py uses -- this exercises the real repository/service
chain against a real database without also depending on a live Temporal
server (Temporal's own orchestration -- sequencing, parallelism, signal/
query -- already has dedicated coverage in
tests/unit/orchestration/temporal/test_analysis_pipeline.py and
test_signal_query.py, against mocked activities).

Requires (same convention as tests/security/tenant_isolation_fuzzer):
    - A running TimescaleDB with migrations 0001+ applied.
    - APP_DATABASE_URL environment variable set to an asyncpg DSN for the
      carbonsense_app role (defaults to
      postgresql+asyncpg://carbonsense_app:changeme@localhost:5432/carbonsense,
      matching shared/config/database.py's DatabaseSettings default).

No trained ML Ensemble model is registered for the test building, so
ml_ensemble_activity's scores carry no if_score/ae_reconstruction_error
and root_cause_attribution_activity correctly persists nothing beyond the
domain-rule finding rule_engine_activity already inserted -- this is the
documented graceful-degradation path (see analysis_stubs.py), not a test
gap.
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text

from orchestration.temporal.activities.analysis_stubs import (
    confidence_calibration_activity,
    data_quality_gate_activity,
    feature_assembly_activity,
    ml_ensemble_activity,
    root_cause_attribution_activity,
    rule_engine_activity,
    stl_detection_activity,
)
from orchestration.temporal.dto import AnalysisPipelineInput
from shared.auth.tenant_context import tenant_scope
from shared.database import get_session_factory

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture()
async def seeded_building() -> AsyncIterator[tuple[uuid.UUID, uuid.UUID, uuid.UUID]]:
    """Seed a tenant, building (with an HVAC-after-hours-triggering
    occupancy schedule), one circuit, three days of normalized_readings
    (including an after-hours spike), and matching building_calendar
    entries -- the minimum real data needed to exercise every layer.
    """
    tenant_id, building_id, circuit_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    today = datetime.date.today()
    factory = get_session_factory()

    async with factory() as session, tenant_scope(session, tenant_id):
        await session.execute(
            text(
                "INSERT INTO tenants (tenant_id, name, isolation_tier) "
                "VALUES (:id, 'e2e-test-tenant', 'shared_rls')"
            ),
            {"id": str(tenant_id)},
        )
        await session.execute(
            text(
                """
                INSERT INTO buildings (
                    building_id, tenant_id, name, building_type, timezone,
                    cold_start, declared_unoccupied_baseline, declared_occupancy_schedule
                ) VALUES (
                    :building_id, :tenant_id, 'e2e-test-building', 'office', 'UTC',
                    false, 0.5, :schedule
                )
                """
            ),
            {
                "building_id": str(building_id),
                "tenant_id": str(tenant_id),
                "schedule": '{"days": [1, 2, 3, 4, 5], "start": "08:00", "end": "18:00"}',
            },
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

        for day_offset in range(3, 0, -1):
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
                # After-hours (22:00) spike well above the declared
                # unoccupied baseline -- triggers hvac_after_hours_v3.
                kwh = 5.0 if hour == 22 else 1.0
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

    yield tenant_id, building_id, circuit_id

    async with factory() as session, tenant_scope(session, tenant_id):
        await session.execute(
            text("DELETE FROM findings WHERE tenant_id = :tid"), {"tid": str(tenant_id)}
        )
        await session.execute(
            text("DELETE FROM normalized_readings WHERE tenant_id = :tid"),
            {"tid": str(tenant_id)},
        )
        await session.execute(
            text("DELETE FROM building_calendar WHERE tenant_id = :tid"), {"tid": str(tenant_id)}
        )
        await session.execute(
            text("DELETE FROM submeter_circuits WHERE tenant_id = :tid"), {"tid": str(tenant_id)}
        )
        await session.execute(
            text("DELETE FROM buildings WHERE tenant_id = :tid"), {"tid": str(tenant_id)}
        )
        await session.execute(
            text("DELETE FROM tenants WHERE tenant_id = :tid"), {"tid": str(tenant_id)}
        )
        await session.commit()


@pytest.mark.asyncio
async def test_full_pipeline_raw_data_to_explainability(
    seeded_building: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    tenant_id, building_id, circuit_id = seeded_building
    input = AnalysisPipelineInput(
        tenant_id=str(tenant_id),
        building_id=str(building_id),
        correlation_id="e2e-test",
        window_days=7,
    )

    gate_output = await data_quality_gate_activity(input)
    assert gate_output.overall_status == "pass"

    rule_output = await rule_engine_activity(input)
    stl_output = await stl_detection_activity(input)

    # The after-hours spike must have produced a real, persisted
    # domain-rule finding -- the whole point of seeding it.
    assert len(rule_output.findings) >= 1
    assert rule_output.findings[0].layer_origin == "domain_rule"
    assert any(f.rule_id == "hvac_after_hours_v3" for f in rule_output.rule_fires)

    feature_output = await feature_assembly_activity(input, rule_output, stl_output)
    assert len(feature_output.features) > 0
    assert all(f.circuit_id == circuit_id for f in feature_output.features)

    ml_output = await ml_ensemble_activity(input, feature_output)
    # No trained model registered for this building -- graceful
    # cold-start degradation, not an error.
    assert all(not s.if_is_anomalous for s in ml_output.scores)

    calibration_output = await confidence_calibration_activity(input, ml_output)

    explainability_output = await root_cause_attribution_activity(
        input, feature_output, calibration_output
    )
    # No ML-ensemble-anomalous scores (no model), so nothing new persists
    # here -- the domain-rule finding from rule_engine_activity already did.
    assert explainability_output.persisted_finding_ids == []

    factory = get_session_factory()
    async with factory() as session, tenant_scope(session, tenant_id):
        result = await session.execute(
            text("SELECT layer_origin, explainability_bundle FROM findings WHERE tenant_id = :tid"),
            {"tid": str(tenant_id)},
        )
        rows = result.fetchall()

    assert len(rows) >= 1
    assert any(row.layer_origin == "domain_rule" for row in rows)
