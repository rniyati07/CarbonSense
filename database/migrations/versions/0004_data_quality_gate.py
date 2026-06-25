"""ENG-3a: Data Quality Gate — alerts table and provenance columns.

Adds:
  - data_quality_alerts table for persisted, tenant-scoped quality alerts
  - Provenance metadata columns on normalized_readings:
    source_system, ingestion_timestamp, normalization_version

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-24
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── Provenance columns on normalized_readings ────────────────────
    op.execute(
        "ALTER TABLE normalized_readings "
        "ADD COLUMN source_system TEXT"
    )
    op.execute(
        "ALTER TABLE normalized_readings "
        "ADD COLUMN ingestion_timestamp TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE normalized_readings "
        "ADD COLUMN normalization_version TEXT NOT NULL DEFAULT 'v1.0.0'"
    )

    # ── Data quality alerts table ────────────────────────────────────
    op.execute("""
        CREATE TABLE data_quality_alerts (
            alert_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,
            building_id UUID NOT NULL,
            alert_type TEXT NOT NULL,
            severity TEXT NOT NULL DEFAULT 'warning',
            message TEXT NOT NULL,
            metadata JSONB,
            acknowledged BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("ALTER TABLE data_quality_alerts ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON data_quality_alerts "
        "USING (tenant_id = current_setting('app.current_tenant_id')::uuid)"
    )
    op.execute("ALTER TABLE data_quality_alerts FORCE ROW LEVEL SECURITY")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE "
        "ON data_quality_alerts TO carbonsense_app"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS data_quality_alerts CASCADE")
    op.execute("ALTER TABLE normalized_readings DROP COLUMN IF EXISTS source_system")
    op.execute("ALTER TABLE normalized_readings DROP COLUMN IF EXISTS ingestion_timestamp")
    op.execute("ALTER TABLE normalized_readings DROP COLUMN IF EXISTS normalization_version")