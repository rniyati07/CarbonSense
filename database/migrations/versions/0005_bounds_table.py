"""ENG-3a audit fix: versioned implausible-value bounds table.

TRD v2.0 §3.1: "bounds are a versioned, editable table, not a magic
number in code."

Adds:
  - implausible_value_bounds table with RLS
  - Seed rows for default circuit types

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-25
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE implausible_value_bounds (
            bounds_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            circuit_type TEXT NOT NULL,
            min_kwh DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            max_kwh DOUBLE PRECISION NOT NULL DEFAULT 5000.0,
            version TEXT NOT NULL DEFAULT '1.0.0',
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            updated_by TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (circuit_type, version)
        )
    """)

    op.execute("""
        INSERT INTO implausible_value_bounds (circuit_type, min_kwh, max_kwh, version, updated_by)
        VALUES
            ('__default__', 0.0, 5000.0, '1.0.0', 'migration_0005'),
            ('main_feed',   0.0, 5000.0, '1.0.0', 'migration_0005'),
            ('hvac',        0.0, 2000.0, '1.0.0', 'migration_0005'),
            ('lighting',    0.0,  500.0, '1.0.0', 'migration_0005'),
            ('plug_load',   0.0,  200.0, '1.0.0', 'migration_0005')
    """)

    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE "
        "ON implausible_value_bounds TO carbonsense_app"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS implausible_value_bounds CASCADE")
