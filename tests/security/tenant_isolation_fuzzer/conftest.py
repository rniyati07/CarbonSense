"""Shared fixtures for the tenant isolation fuzzer.

Creates two fully isolated test tenants (tenant_a, tenant_b) with sample
buildings, circuits, readings, findings, and feedback_labels. All tests
run against a real TimescaleDB instance using the carbonsense_app role
(non-superuser) with RLS enforced — no mocking.

Requires:
    - A running TimescaleDB with migrations 0001-0003 applied.
    - DATABASE_URL environment variable set.
    - The carbonsense_app role configured with LOGIN and a password.
    - APP_DATABASE_URL environment variable set for app-role connections.
"""

from __future__ import annotations

import datetime
import os
import uuid
from collections.abc import Generator

import pytest
import sqlalchemy as sa
from sqlalchemy import text

ADMIN_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://carbonsense:changeme@localhost:5432/carbonsense",
)
APP_URL = os.environ.get(
    "APP_DATABASE_URL",
    "postgresql://carbonsense_app:changeme@localhost:5432/carbonsense",
)


@pytest.fixture(scope="session")
def admin_engine() -> Generator[sa.Engine, None, None]:
    """Admin-privileged engine for setup/teardown only."""
    engine = sa.create_engine(ADMIN_URL)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def app_engine() -> Generator[sa.Engine, None, None]:
    """App-role engine — the role application connections actually use."""
    engine = sa.create_engine(APP_URL)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def tenant_a_id() -> uuid.UUID:
    return uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


@pytest.fixture(scope="session")
def tenant_b_id() -> uuid.UUID:
    return uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


@pytest.fixture(scope="session", autouse=True)
def seed_test_data(
    admin_engine: sa.Engine,
    tenant_a_id: uuid.UUID,
    tenant_b_id: uuid.UUID,
) -> Generator[None, None, None]:
    """Seed two tenants with sample data, clean up after all tests."""
    with admin_engine.begin() as conn:
        # Clean up any prior test data
        _cleanup(conn, tenant_a_id, tenant_b_id)

        # Create tenants
        for tid, name in [
            (tenant_a_id, "Test Tenant A"),
            (tenant_b_id, "Test Tenant B"),
        ]:
            conn.execute(
                text("""
                    INSERT INTO tenants (tenant_id, name, isolation_tier)
                    VALUES (:tid, :name, 'shared_rls')
                """),
                {"tid": str(tid), "name": name},
            )

        # Create buildings
        building_a = uuid.UUID("a1111111-1111-1111-1111-111111111111")
        building_b = uuid.UUID("b1111111-1111-1111-1111-111111111111")

        for bid, tid, name in [
            (building_a, tenant_a_id, "Building A"),
            (building_b, tenant_b_id, "Building B"),
        ]:
            conn.execute(
                text("""
                    INSERT INTO buildings
                        (building_id, tenant_id, name, building_type, timezone)
                    VALUES (:bid, :tid, :name, 'office', 'Asia/Kolkata')
                """),
                {"bid": str(bid), "tid": str(tid), "name": name},
            )

        # Create circuits
        circuit_a = uuid.UUID("a2222222-2222-2222-2222-222222222222")
        circuit_b = uuid.UUID("b2222222-2222-2222-2222-222222222222")

        for cid, tid, bid in [
            (circuit_a, tenant_a_id, building_a),
            (circuit_b, tenant_b_id, building_b),
        ]:
            conn.execute(
                text("""
                    INSERT INTO submeter_circuits
                        (circuit_id, tenant_id, building_id, circuit_type)
                    VALUES (:cid, :tid, :bid, 'hvac')
                """),
                {"cid": str(cid), "tid": str(tid), "bid": str(bid)},
            )

        # Create readings
        ts = datetime.datetime(2026, 6, 1, tzinfo=datetime.UTC)
        for tid, cid in [(tenant_a_id, circuit_a), (tenant_b_id, circuit_b)]:
            conn.execute(
                text("""
                    INSERT INTO normalized_readings
                        (tenant_id, circuit_id, ts, kwh, data_quality_status)
                    VALUES (:tid, :cid, :ts, 42.0, 'pass')
                """),
                {"tid": str(tid), "cid": str(cid), "ts": ts},
            )

        # Create findings
        finding_a = uuid.UUID("a3333333-3333-3333-3333-333333333333")
        finding_b = uuid.UUID("b3333333-3333-3333-3333-333333333333")

        for fid, tid, bid in [
            (finding_a, tenant_a_id, building_a),
            (finding_b, tenant_b_id, building_b),
        ]:
            conn.execute(
                text("""
                    INSERT INTO findings
                        (finding_id, tenant_id, building_id, layer_origin,
                         evidence_window, explainability_bundle)
                    VALUES (
                        :fid, :tid, :bid, 'domain_rule',
                        tstzrange(:start, :end),
                        '{"test": true}'::jsonb
                    )
                """),
                {
                    "fid": str(fid),
                    "tid": str(tid),
                    "bid": str(bid),
                    "start": ts,
                    "end": ts + datetime.timedelta(hours=1),
                },
            )

        # Create feedback_labels
        for tid, fid in [(tenant_a_id, finding_a), (tenant_b_id, finding_b)]:
            conn.execute(
                text("""
                    INSERT INTO feedback_labels
                        (tenant_id, finding_id, action, actor)
                    VALUES (:tid, :fid, 'confirmed', 'test_user')
                """),
                {"tid": str(tid), "fid": str(fid)},
            )

        # Create audit_log entries
        for tid in [tenant_a_id, tenant_b_id]:
            conn.execute(
                text("""
                    INSERT INTO audit_log (tenant_id, event_type, payload)
                    VALUES (:tid, 'test.seeded', '{"test": true}'::jsonb)
                """),
                {"tid": str(tid)},
            )

        # Create building_calendar entries
        for tid, bid in [(tenant_a_id, building_a), (tenant_b_id, building_b)]:
            conn.execute(
                text("""
                    INSERT INTO building_calendar
                        (tenant_id, building_id, date, day_type, source)
                    VALUES (:tid, :bid, '2026-06-01', 'business_day', 'test')
                """),
                {"tid": str(tid), "bid": str(bid)},
            )

    yield

    with admin_engine.begin() as conn:
        _cleanup(conn, tenant_a_id, tenant_b_id)


def _cleanup(
    conn: sa.Connection,
    tenant_a_id: uuid.UUID,
    tenant_b_id: uuid.UUID,
) -> None:
    """Remove all test data in FK-safe order."""
    for tid in [str(tenant_a_id), str(tenant_b_id)]:
        conn.execute(
            text("DELETE FROM feedback_labels WHERE tenant_id = :tid"),
            {"tid": tid},
        )
        conn.execute(
            text("DELETE FROM findings WHERE tenant_id = :tid"),
            {"tid": tid},
        )
        conn.execute(
            text("DELETE FROM building_calendar WHERE tenant_id = :tid"),
            {"tid": tid},
        )
        conn.execute(
            text("DELETE FROM normalized_readings WHERE tenant_id = :tid"),
            {"tid": tid},
        )
        conn.execute(
            text("DELETE FROM submeter_circuits WHERE tenant_id = :tid"),
            {"tid": tid},
        )
        conn.execute(
            text("DELETE FROM buildings WHERE tenant_id = :tid"),
            {"tid": tid},
        )
        conn.execute(
            text("DELETE FROM audit_log WHERE tenant_id = :tid"),
            {"tid": tid},
        )
        conn.execute(
            text("DELETE FROM tenants WHERE tenant_id = :tid"),
            {"tid": tid},
        )
