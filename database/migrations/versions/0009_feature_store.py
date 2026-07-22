"""ENG-6: Feature Store persistence.

feature_assembly_activity (orchestration/temporal/activities/analysis_stubs.py)
has computed FeatureSetV1 rows on every AnalysisPipelineWorkflow run since
ENG-3d-1, but nothing has ever persisted them -- FeatureAssemblyOutput is
passed in-memory to ml_ensemble_activity and root_cause_attribution_activity
within that single workflow execution and then discarded. This is the exact
reason _fetch_training_features() in orchestration/temporal/activities/
ml_ensemble_activities.py has been a TODO(ENG-6b) stub returning an empty
list since ENG-3d: there was never anywhere for it to query. This migration
adds that missing table.

Schema mirrors models.feature_store.feature_set_v1.FeatureSetV1's fields
directly (one column per feature, not a JSONB blob) so training-window
queries can filter/aggregate in SQL rather than deserializing every row.
rule_fire_indicators is the one dict-shaped field and stays JSONB, matching
findings.explainability_bundle's own precedent for a variable-shaped field.

Primary key (tenant_id, circuit_id, ts) matches normalized_readings' own
primary key shape -- one feature row per (circuit, timestamp), consistent
with FeatureAssembler.assemble() producing exactly one FeatureSetV1 per
input NormalizedReading. Re-running feature assembly for an
already-featurized window (e.g. a re-triggered analysis run) upserts rather
than duplicating.

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-19
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE feature_store (
            tenant_id UUID NOT NULL,
            circuit_id UUID NOT NULL REFERENCES submeter_circuits(circuit_id),
            ts TIMESTAMPTZ NOT NULL,
            feature_schema_version TEXT NOT NULL DEFAULT 'feature_set_v1',
            rolling_baseline_kwh DOUBLE PRECISION,
            peak_offpeak_split DOUBLE PRECISION,
            after_hours_kwh_ratio DOUBLE PRECISION,
            weekend_floor_load DOUBLE PRECISION,
            rolling_efficiency_ratio DOUBLE PRECISION,
            stl_residual_magnitude DOUBLE PRECISION,
            day_type TEXT NOT NULL DEFAULT 'business_day',
            rule_fire_indicators JSONB NOT NULL DEFAULT '{}'::jsonb,
            low_data_quality BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, circuit_id, ts)
        )
    """)
    op.execute("SELECT create_hypertable('feature_store', 'ts')")
    op.execute("ALTER TABLE feature_store ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON feature_store "
        "USING (tenant_id = current_setting('app.current_tenant_id')::uuid)"
    )
    op.execute("ALTER TABLE feature_store FORCE ROW LEVEL SECURITY")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON feature_store TO carbonsense_app")


def downgrade() -> None:
    op.execute("ALTER TABLE feature_store NO FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON feature_store")
    op.execute("DROP TABLE IF EXISTS feature_store CASCADE")
