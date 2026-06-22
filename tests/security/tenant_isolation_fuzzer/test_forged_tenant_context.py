"""ENG-1f: Forged/mismatched tenant context tests.

Test (b) from the fuzzer spec:
  A forged or mismatched token tenant claim.

Tests that RLS denies access when:
  - No tenant context is set (app.current_tenant_id unset)
  - Tenant context is set to a non-existent UUID
  - Tenant context is switched mid-session to another tenant's ID
  - Tenant context is set to an invalid (non-UUID) value

These tests are CI-blocking — same severity as a failing build.
"""

from __future__ import annotations

import contextlib
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
class TestUnsetTenantContext:
    """Queries without setting app.current_tenant_id should fail or
    return zero rows."""

    @pytest.mark.parametrize("table", TENANT_SCOPED_TABLES)
    def test_query_without_tenant_context_fails(
        self,
        app_engine: sa.Engine,
        table: str,
    ) -> None:
        """Without SET app.current_tenant_id, all queries should either
        raise an error or return zero rows."""
        with app_engine.begin() as conn:
            # Explicitly reset to ensure no context is set
            with contextlib.suppress(sa.exc.DBAPIError):
                conn.execute(text("RESET app.current_tenant_id"))

            try:
                result = conn.execute(
                    text(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
                )
                count = result.scalar()
                assert count == 0, (
                    f"RLS BREACH: query on {table} without tenant context returned {count} rows"
                )
            except sa.exc.DBAPIError:
                # An error is also acceptable — it means RLS blocked
                # the query because current_setting() failed on the
                # unset variable, which is fail-closed behavior.
                pass


@pytest.mark.security
class TestNonExistentTenantContext:
    """Setting tenant context to a UUID that doesn't exist in the tenants
    table should return zero rows (RLS compares UUIDs, not existence)."""

    @pytest.mark.parametrize("table", TENANT_SCOPED_TABLES)
    def test_nonexistent_tenant_sees_nothing(
        self,
        app_engine: sa.Engine,
        table: str,
    ) -> None:
        fake_tenant = uuid.UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
        with app_engine.begin() as conn:
            conn.execute(
                text("SET LOCAL app.current_tenant_id = :tid"),
                {"tid": str(fake_tenant)},
            )
            result = conn.execute(text(f"SELECT COUNT(*) FROM {table}"))  # noqa: S608
            count = result.scalar()
            assert count == 0, (
                f"RLS BREACH: non-existent tenant context returned {count} rows from {table}"
            )


@pytest.mark.security
class TestTenantContextSwitching:
    """Switching tenant context mid-session should immediately change
    visibility. After switching from A to B, tenant A's data must
    become invisible."""

    def test_context_switch_hides_previous_tenant_data(
        self,
        app_engine: sa.Engine,
        tenant_a_id: uuid.UUID,
        tenant_b_id: uuid.UUID,
    ) -> None:
        with app_engine.begin() as conn:
            # Set context to tenant A, verify data is visible
            conn.execute(
                text("SET LOCAL app.current_tenant_id = :tid"),
                {"tid": str(tenant_a_id)},
            )
            a_count = conn.execute(text("SELECT COUNT(*) FROM buildings")).scalar()
            assert a_count is not None and a_count > 0, (
                "Setup error: tenant A should have buildings"
            )

            # Switch to tenant B
            conn.execute(
                text("SET LOCAL app.current_tenant_id = :tid"),
                {"tid": str(tenant_b_id)},
            )

            # Tenant A's buildings should now be invisible
            a_visible = conn.execute(
                text("SELECT COUNT(*) FROM buildings WHERE tenant_id = :tid"),
                {"tid": str(tenant_a_id)},
            ).scalar()
            assert a_visible == 0, (
                f"RLS BREACH: after switching to tenant B context, "
                f"tenant A's buildings are still visible ({a_visible} rows)"
            )

    def test_context_switch_to_forged_id_hides_all(
        self,
        app_engine: sa.Engine,
        tenant_a_id: uuid.UUID,
    ) -> None:
        """Start with valid context, then switch to a forged UUID.
        Everything should become invisible."""
        forged = uuid.UUID("deadbeef-dead-beef-dead-beefdeadbeef")
        with app_engine.begin() as conn:
            # Start with valid context
            conn.execute(
                text("SET LOCAL app.current_tenant_id = :tid"),
                {"tid": str(tenant_a_id)},
            )
            initial = conn.execute(text("SELECT COUNT(*) FROM buildings")).scalar()
            assert initial is not None and initial > 0

            # Switch to forged context
            conn.execute(
                text("SET LOCAL app.current_tenant_id = :tid"),
                {"tid": str(forged)},
            )
            after = conn.execute(text("SELECT COUNT(*) FROM buildings")).scalar()
            assert after == 0, f"RLS BREACH: forged tenant context sees {after} buildings"


@pytest.mark.security
class TestInvalidTenantContext:
    """Setting tenant context to an invalid value should cause queries
    to fail (the ::uuid cast should error)."""

    def test_non_uuid_context_causes_error(
        self,
        app_engine: sa.Engine,
    ) -> None:
        with app_engine.begin() as conn:
            conn.execute(text("SET LOCAL app.current_tenant_id = 'not-a-uuid'"))
            with pytest.raises(sa.exc.DBAPIError):
                conn.execute(text("SELECT * FROM buildings"))

    def test_empty_string_context_causes_error(
        self,
        app_engine: sa.Engine,
    ) -> None:
        with app_engine.begin() as conn:
            conn.execute(text("SET LOCAL app.current_tenant_id = ''"))
            with pytest.raises(sa.exc.DBAPIError):
                conn.execute(text("SELECT * FROM buildings"))
