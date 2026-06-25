-- CarbonSense Canonical Schema — READ-ONLY REFERENCE
--
-- ⚠  DO NOT APPLY THIS FILE TO ANY DATABASE. ⚠
--
-- This file is a human-readable snapshot of the schema for documentation
-- and code review. It is NOT used by any automated process.
--
-- The single source of truth for all schema changes — across ALL isolation
-- tiers (shared_rls, dedicated_schema, dedicated_db) — is:
--
--     database/migrations/versions/  (Alembic)
--
-- Terraform provisions dedicated tiers by running `alembic upgrade head`
-- against the target database/schema. There is no separate DDL path.
--
-- If this file diverges from the migrations, the migrations win.
-- Last synced with: migration 0003 (2026-06-21)
--
-- TimescaleDB and pgcrypto extensions required.

CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ================================================================
-- Tenancy & topology (migration 0001)
-- ================================================================

CREATE TABLE tenants (
    tenant_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    isolation_tier TEXT NOT NULL
        CHECK (isolation_tier IN ('shared_rls', 'dedicated_schema', 'dedicated_db')),
    retention_policy JSONB,
    cross_tenant_aggregate_opt_in BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

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
);
ALTER TABLE buildings ENABLE ROW LEVEL SECURITY;

CREATE TABLE submeter_circuits (
    circuit_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(tenant_id),
    building_id UUID NOT NULL REFERENCES buildings(building_id),
    parent_circuit_id UUID REFERENCES submeter_circuits(circuit_id),
    panel_id TEXT,
    floor TEXT,
    circuit_type TEXT NOT NULL,
    label TEXT
);
ALTER TABLE submeter_circuits ENABLE ROW LEVEL SECURITY;

-- ================================================================
-- Time-series (TimescaleDB hypertable) (migration 0001)
-- ================================================================

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
);
SELECT create_hypertable('normalized_readings', 'ts');
ALTER TABLE normalized_readings ENABLE ROW LEVEL SECURITY;

-- ================================================================
-- Findings & audit (migration 0001)
-- ================================================================

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
);
ALTER TABLE findings ENABLE ROW LEVEL SECURITY;

CREATE TABLE feedback_labels (
    feedback_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    finding_id UUID NOT NULL REFERENCES findings(finding_id),
    action TEXT NOT NULL CHECK (action IN ('confirmed', 'dismissed')),
    actor TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE feedback_labels ENABLE ROW LEVEL SECURITY;

CREATE TABLE audit_log (
    audit_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    event_type TEXT NOT NULL,
    entity_id UUID,
    payload JSONB NOT NULL,
    model_version TEXT,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
-- audit_log is append-only: no UPDATE/DELETE grants for the app role.

-- ================================================================
-- Building calendar (migration 0001, ENG-1d)
-- ================================================================

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
);
ALTER TABLE building_calendar ENABLE ROW LEVEL SECURITY;

-- ================================================================
-- Application role (migration 0001)
-- ================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'carbonsense_app'
    ) THEN
        CREATE ROLE carbonsense_app NOLOGIN;
    END IF;
END
$$;

GRANT SELECT, INSERT, UPDATE, DELETE ON tenants TO carbonsense_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON buildings TO carbonsense_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON submeter_circuits TO carbonsense_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON normalized_readings TO carbonsense_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON findings TO carbonsense_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON feedback_labels TO carbonsense_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON building_calendar TO carbonsense_app;

GRANT SELECT, INSERT ON audit_log TO carbonsense_app;
REVOKE UPDATE, DELETE ON audit_log FROM carbonsense_app;

-- ================================================================
-- RLS policies (migration 0002)
-- ================================================================

CREATE POLICY tenant_isolation ON buildings
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);
ALTER TABLE buildings FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON submeter_circuits
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);
ALTER TABLE submeter_circuits FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON normalized_readings
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);
ALTER TABLE normalized_readings FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON findings
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);
ALTER TABLE findings FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON feedback_labels
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);
ALTER TABLE feedback_labels FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON audit_log
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);
ALTER TABLE audit_log FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON building_calendar
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);
ALTER TABLE building_calendar FORCE ROW LEVEL SECURITY;

-- ================================================================
-- Deletion cascade functions (migration 0003)
-- ================================================================

-- See database/migrations/versions/0003_retention_and_deletion.py
-- for the full PL/pgSQL function bodies of:
--   delete_building_data(UUID, UUID)
--   delete_tenant_data(UUID)

-- ================================================================
-- Provenance columns on normalized_readings (migration 0004, ENG-3a)
-- ================================================================

-- ALTER TABLE normalized_readings ADD COLUMN source_system TEXT;
-- ALTER TABLE normalized_readings ADD COLUMN ingestion_timestamp TIMESTAMPTZ;
-- ALTER TABLE normalized_readings ADD COLUMN normalization_version TEXT NOT NULL DEFAULT 'v1.0.0';

-- ================================================================
-- Data quality alerts (migration 0004, ENG-3a)
-- ================================================================

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
);
ALTER TABLE data_quality_alerts ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON data_quality_alerts
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);
ALTER TABLE data_quality_alerts FORCE ROW LEVEL SECURITY;

GRANT SELECT, INSERT, UPDATE, DELETE ON data_quality_alerts TO carbonsense_app;

-- ================================================================
-- Implausible-value bounds (migration 0005, ENG-3a audit fix)
-- TRD v2.0 §3.1: "a versioned, editable table, not a magic number"
-- ================================================================

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
);

GRANT SELECT, INSERT, UPDATE, DELETE ON implausible_value_bounds TO carbonsense_app;