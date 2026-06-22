"""ENG-1f: RLS enforcement tests — cross-tenant read/write attempts.

Tests (a) and (c) from the fuzzer spec:
  (a) Cross-tenant read/write with wrong tenant_id in a query.
  (c) A retraining-job-style call parameterized with another tenant's ID.

Every test asserts that the attempt FAILS CLOSED: zero rows returned
for reads, zero rows written for writes, and no exceptions that would
leak information about the other tenant's data.

These tests are CI-blocking — same severity as a failing build
(TECH_STACK_LOCK §5.2, ROADMAP ENG-1f).
"""

from __future__ import annotations

import datetime
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy import text

TENANT_SCOPED_TABLES = [
    "buildings",
    "submeter_circuits",
    "normalized_readings",
    "findings",
    "feedback_labels",
    "audit_log",
    "building_calendar",
]


@pytest.mark.security
class TestCrossTenantReads:
    """(a) Attempt to read another tenant's data with wrong tenant context."""

    @pytest.mark.parametrize("table", TENANT_SCOPED_TABLES)
    def test_select_returns_zero_rows_for_wrong_tenant(
        self,
        app_engine: sa.Engine,
        tenant_a_id: uuid.UUID,
        tenant_b_id: uuid.UUID,
        table: str,
    ) -> None:
        """Setting tenant context to A and querying should return zero
        rows belonging to tenant B."""
        with app_engine.begin() as conn:
            conn.execute(
                text("SET LOCAL app.current_tenant_id = :tid"),
                {"tid": str(tenant_a_id)},
            )
            result = conn.execute(
                text(f"SELECT COUNT(*) FROM {table} WHERE tenant_id = :other_tid"),  # noqa: S608
                {"other_tid": str(tenant_b_id)},
            )
            count = result.scalar()
            assert count == 0, (
                f"RLS BREACH: tenant A context saw {count} rows from tenant B in {table}"
            )

    @pytest.mark.parametrize("table", TENANT_SCOPED_TABLES)
    def test_select_without_where_only_returns_own_rows(
        self,
        app_engine: sa.Engine,
        tenant_a_id: uuid.UUID,
        tenant_b_id: uuid.UUID,
        table: str,
    ) -> None:
        """A SELECT * (no WHERE tenant_id = ...) should still only
        return the current tenant's rows, never the other's."""
        with app_engine.begin() as conn:
            conn.execute(
                text("SET LOCAL app.current_tenant_id = :tid"),
                {"tid": str(tenant_a_id)},
            )
            result = conn.execute(text(f"SELECT tenant_id FROM {table}"))  # noqa: S608
            rows = result.fetchall()
            for row in rows:
                assert str(row[0]) == str(tenant_a_id), (
                    f"RLS BREACH: tenant A context returned row with "
                    f"tenant_id={row[0]} from {table}"
                )


@pytest.mark.security
class TestCrossTenantWrites:
    """(a) Attempt to write data with another tenant's tenant_id."""

    def test_insert_reading_with_wrong_tenant_id_fails(
        self,
        app_engine: sa.Engine,
        tenant_a_id: uuid.UUID,
        tenant_b_id: uuid.UUID,
    ) -> None:
        """Set context to tenant A, attempt to insert a reading with
        tenant B's ID. RLS should block this."""
        circuit_b = uuid.UUID("b2222222-2222-2222-2222-222222222222")
        with app_engine.begin() as conn:
            conn.execute(
                text("SET LOCAL app.current_tenant_id = :tid"),
                {"tid": str(tenant_a_id)},
            )
            # The INSERT should either fail or the row should be invisible
            try:
                conn.execute(
                    text("""
                        INSERT INTO normalized_readings
                            (tenant_id, circuit_id, ts, kwh, data_quality_status)
                        VALUES (:tid, :cid, :ts, 99.9, 'pass')
                    """),
                    {
                        "tid": str(tenant_b_id),
                        "cid": str(circuit_b),
                        "ts": datetime.datetime(2026, 7, 1, tzinfo=datetime.UTC),
                    },
                )
                # If INSERT succeeded, verify the row is not visible
                count = conn.execute(
                    text("""
                        SELECT COUNT(*) FROM normalized_readings
                        WHERE tenant_id = :tid AND ts = :ts
                    """),
                    {
                        "tid": str(tenant_b_id),
                        "ts": datetime.datetime(2026, 7, 1, tzinfo=datetime.UTC),
                    },
                ).scalar()
                assert count == 0, "RLS BREACH: cross-tenant INSERT succeeded and row is visible"
            except sa.exc.DBAPIError:
                # RLS correctly blocked the INSERT — this is the expected path
                pass

    def test_update_other_tenants_building_fails(
        self,
        app_engine: sa.Engine,
        tenant_a_id: uuid.UUID,
        tenant_b_id: uuid.UUID,
    ) -> None:
        """Set context to tenant A, attempt to UPDATE tenant B's building."""
        with app_engine.begin() as conn:
            conn.execute(
                text("SET LOCAL app.current_tenant_id = :tid"),
                {"tid": str(tenant_a_id)},
            )
            result = conn.execute(
                text("""
                    UPDATE buildings SET name = 'HACKED'
                    WHERE tenant_id = :other_tid
                """),
                {"other_tid": str(tenant_b_id)},
            )
            assert result.rowcount == 0, "RLS BREACH: cross-tenant UPDATE modified rows"

    def test_delete_other_tenants_findings_fails(
        self,
        app_engine: sa.Engine,
        tenant_a_id: uuid.UUID,
        tenant_b_id: uuid.UUID,
    ) -> None:
        """Set context to tenant A, attempt to DELETE tenant B's findings."""
        with app_engine.begin() as conn:
            conn.execute(
                text("SET LOCAL app.current_tenant_id = :tid"),
                {"tid": str(tenant_a_id)},
            )
            result = conn.execute(
                text("""
                    DELETE FROM findings WHERE tenant_id = :other_tid
                """),
                {"other_tid": str(tenant_b_id)},
            )
            assert result.rowcount == 0, "RLS BREACH: cross-tenant DELETE removed rows"


@pytest.mark.security
class TestRetrainingJobIsolation:
    """(c) Simulated retraining-job query parameterized with another
    tenant's ID. Per TRD §3.8: a misconfigured retraining job cannot
    pull another tenant's rows because the database itself enforces
    isolation, not application discipline."""

    def test_training_data_query_with_wrong_tenant_returns_empty(
        self,
        app_engine: sa.Engine,
        tenant_a_id: uuid.UUID,
        tenant_b_id: uuid.UUID,
    ) -> None:
        """Simulate a retraining job that sets tenant_a context but
        queries for tenant_b's training data."""
        with app_engine.begin() as conn:
            conn.execute(
                text("SET LOCAL app.current_tenant_id = :tid"),
                {"tid": str(tenant_a_id)},
            )
            # Simulated training-data query: get readings + feedback for a building
            readings = conn.execute(
                text("""
                    SELECT nr.kwh, nr.ts
                    FROM normalized_readings nr
                    WHERE nr.tenant_id = :other_tid
                """),
                {"other_tid": str(tenant_b_id)},
            ).fetchall()
            assert len(readings) == 0, (
                f"RLS BREACH: retraining job with tenant A context "
                f"retrieved {len(readings)} readings from tenant B"
            )

    def test_training_labels_query_with_wrong_tenant_returns_empty(
        self,
        app_engine: sa.Engine,
        tenant_a_id: uuid.UUID,
        tenant_b_id: uuid.UUID,
    ) -> None:
        """Simulate fetching feedback labels for model evaluation
        with the wrong tenant context."""
        with app_engine.begin() as conn:
            conn.execute(
                text("SET LOCAL app.current_tenant_id = :tid"),
                {"tid": str(tenant_a_id)},
            )
            labels = conn.execute(
                text("""
                    SELECT fl.action, fl.finding_id
                    FROM feedback_labels fl
                    JOIN findings f ON f.finding_id = fl.finding_id
                    WHERE fl.tenant_id = :other_tid
                """),
                {"other_tid": str(tenant_b_id)},
            ).fetchall()
            assert len(labels) == 0, (
                f"RLS BREACH: retraining job with tenant A context "
                f"retrieved {len(labels)} labels from tenant B"
            )

    def test_cross_tenant_join_returns_empty(
        self,
        app_engine: sa.Engine,
        tenant_a_id: uuid.UUID,
        tenant_b_id: uuid.UUID,
    ) -> None:
        """A join across tenant-scoped tables should never return rows
        from a different tenant, even if the query explicitly asks."""
        with app_engine.begin() as conn:
            conn.execute(
                text("SET LOCAL app.current_tenant_id = :tid"),
                {"tid": str(tenant_a_id)},
            )
            results = conn.execute(
                text("""
                    SELECT b.name, sc.circuit_type, nr.kwh
                    FROM buildings b
                    JOIN submeter_circuits sc ON sc.building_id = b.building_id
                    JOIN normalized_readings nr ON nr.circuit_id = sc.circuit_id
                    WHERE b.tenant_id = :other_tid
                """),
                {"other_tid": str(tenant_b_id)},
            ).fetchall()
            assert len(results) == 0, f"RLS BREACH: cross-tenant JOIN returned {len(results)} rows"
