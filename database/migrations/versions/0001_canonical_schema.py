"""ENG-1a: Canonical multi-tenant schema with TimescaleDB.

Creates all tenant-scoped tables per TRD v2.0 §2.2 verbatim DDL,
plus building_calendar (ENG-1d). Enables RLS on every tenant-scoped
table. Restricts audit_log to INSERT/SELECT only for the app role.

Revision ID: 0001
Revises: None
Create Date: 2026-06-21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── Extension: TimescaleDB ────────────────────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE")

    # ── Extension: pgcrypto for gen_random_uuid() on PG < 14 ─────────
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # ── Tenancy & topology ────────────────────────────────────────────

    op.execute("""
        CREATE TABLE tenants (
            tenant_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name TEXT NOT NULL,
            isolation_tier TEXT NOT NULL
                CHECK (isolation_tier IN ('shared_rls', 'dedicated_schema', 'dedicated_db')),
            retention_policy JSONB,
            cross_tenant_aggregate_opt_in BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE TABLE buildings (
            building_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(tenant_id),
            name TEXT NOT NULL,
            building_type TEXT NOT NULL,
            timezone TEXT NOT NULL,
            climate_zone TEXT,
            cold_start BOOLEAN NOT NULL DEFAULT TRUE,
            declared_unoccupied_baseline DOUBLE PRECISION,
            declared_occupancy_schedule JSONB,
            onboarded_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("ALTER TABLE buildings ENABLE ROW LEVEL SECURITY")

    op.execute("""
        CREATE TABLE submeter_circuits (
            circuit_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(tenant_id),
            building_id UUID NOT NULL REFERENCES buildings(building_id),
            parent_circuit_id UUID REFERENCES submeter_circuits(circuit_id),
            panel_id TEXT,
            floor TEXT,
            circuit_type TEXT NOT NULL,
            label TEXT
        )
    """)
    op.execute("ALTER TABLE submeter_circuits ENABLE ROW LEVEL SECURITY")

    # ── Time-series (TimescaleDB hypertable) ──────────────────────────

    op.execute("""
        CREATE TABLE normalized_readings (
            tenant_id UUID NOT NULL,
            circuit_id UUID NOT NULL REFERENCES submeter_circuits(circuit_id),
            ts TIMESTAMPTZ NOT NULL,
            kwh DOUBLE PRECISION,
            is_peak_hour BOOLEAN,
            rolling_baseline_kwh DOUBLE PRECISION,
            data_quality_status TEXT NOT NULL DEFAULT 'pass',
            schema_version TEXT NOT NULL DEFAULT 'normalized_reading_v1',
            PRIMARY KEY (tenant_id, circuit_id, ts)
        )
    """)
    op.execute("SELECT create_hypertable('normalized_readings', 'ts')")
    op.execute("ALTER TABLE normalized_readings ENABLE ROW LEVEL SECURITY")

    # ── Findings & audit ──────────────────────────────────────────────

    op.execute("""
        CREATE TABLE findings (
            finding_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,
            building_id UUID NOT NULL,
            circuit_id UUID,
            layer_origin TEXT NOT NULL,
            detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            evidence_window TSTZRANGE NOT NULL,
            confidence DOUBLE PRECISION,
            status TEXT NOT NULL DEFAULT 'open'
                CHECK (status IN ('open', 'confirmed', 'dismissed')),
            explainability_bundle JSONB NOT NULL
        )
    """)
    op.execute("ALTER TABLE findings ENABLE ROW LEVEL SECURITY")

    op.execute("""
        CREATE TABLE feedback_labels (
            feedback_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,
            finding_id UUID NOT NULL REFERENCES findings(finding_id),
            action TEXT NOT NULL CHECK (action IN ('confirmed', 'dismissed')),
            actor TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("ALTER TABLE feedback_labels ENABLE ROW LEVEL SECURITY")

    op.execute("""
        CREATE TABLE audit_log (
            audit_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,
            event_type TEXT NOT NULL,
            entity_id UUID,
            payload JSONB NOT NULL,
            model_version TEXT,
            occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY")

    # ── ENG-1d: Building calendar ─────────────────────────────────────

    op.execute("""
        CREATE TABLE building_calendar (
            tenant_id UUID NOT NULL REFERENCES tenants(tenant_id),
            building_id UUID NOT NULL REFERENCES buildings(building_id),
            date DATE NOT NULL,
            day_type TEXT NOT NULL
                CHECK (day_type IN (
                    'business_day', 'weekend', 'holiday', 'declared_closure'
                )),
            source TEXT,
            PRIMARY KEY (tenant_id, building_id, date)
        )
    """)
    op.execute("ALTER TABLE building_calendar ENABLE ROW LEVEL SECURITY")

    # ── App role: restricted permissions ──────────────────────────────
    # The carbonsense_app role is the only role used by application
    # connections. It must never be a superuser. audit_log gets
    # INSERT + SELECT only — no UPDATE or DELETE.

    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_roles WHERE rolname = 'carbonsense_app'
            ) THEN
                CREATE ROLE carbonsense_app NOLOGIN;
            END IF;
        END
        $$
    """)

    _all_tables = [
        "tenants",
        "buildings",
        "submeter_circuits",
        "normalized_readings",
        "findings",
        "feedback_labels",
        "building_calendar",
    ]
    for table in _all_tables:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO carbonsense_app")

    # audit_log: INSERT + SELECT only — explicitly revoke UPDATE/DELETE
    op.execute("GRANT SELECT, INSERT ON audit_log TO carbonsense_app")
    op.execute("REVOKE UPDATE, DELETE ON audit_log FROM carbonsense_app")


def downgrade() -> None:
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM carbonsense_app")
    op.execute("DROP TABLE IF EXISTS building_calendar CASCADE")
    op.execute("DROP TABLE IF EXISTS audit_log CASCADE")
    op.execute("DROP TABLE IF EXISTS feedback_labels CASCADE")
    op.execute("DROP TABLE IF EXISTS findings CASCADE")
    op.execute("DROP TABLE IF EXISTS normalized_readings CASCADE")
    op.execute("DROP TABLE IF EXISTS submeter_circuits CASCADE")
    op.execute("DROP TABLE IF EXISTS buildings CASCADE")
    op.execute("DROP TABLE IF EXISTS tenants CASCADE")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_roles WHERE rolname = 'carbonsense_app'
            ) THEN
                DROP ROLE carbonsense_app;
            END IF;
        END
        $$
    """)
