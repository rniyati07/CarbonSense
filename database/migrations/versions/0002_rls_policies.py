"""ENG-1b: Row-Level Security policies for tenant isolation.

Applies a uniform tenant_isolation policy to every tenant-scoped table
using a parameterized helper — one function, seven calls, not seven
hand-written copies.

Policy pattern:
    CREATE POLICY tenant_isolation ON <table>
      USING (tenant_id = current_setting('app.current_tenant_id')::uuid);

The application sets app.current_tenant_id once per request from the
validated token's tenant claim (shared/auth/tenant_context.py).

No superuser-bypass role is used by application connections.

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_SCOPED_TABLES: list[str] = [
    "buildings",
    "submeter_circuits",
    "normalized_readings",
    "findings",
    "feedback_labels",
    "audit_log",
    "building_calendar",
]


def _apply_tenant_isolation_policy(table: str) -> None:
    """Apply the standard tenant_isolation RLS policy to a table.

    Every tenant-scoped table gets the identical policy: rows are visible
    only when tenant_id matches the session variable app.current_tenant_id.
    FORCE ROW LEVEL SECURITY ensures the policy applies even to the table
    owner, closing the superuser-bypass vector for application connections.
    """
    op.execute(f"""
        CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = current_setting('app.current_tenant_id')::uuid)
    """)
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def _drop_tenant_isolation_policy(table: str) -> None:
    """Remove the tenant_isolation policy from a table."""
    op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")


def upgrade() -> None:
    for table in TENANT_SCOPED_TABLES:
        _apply_tenant_isolation_policy(table)


def downgrade() -> None:
    for table in TENANT_SCOPED_TABLES:
        _drop_tenant_isolation_policy(table)
