"""ENG-4: Optimization Engine — building declared metadata + model-quality incidents.

TRD v2.0 §4 and DATA_AND_MODEL_STRATEGY §3.4/3.6 specify that `load_shift_v1`
needs a "declared tariff schedule" and `solar_offset_v1` is "gated on building
having usable rooftop/location data" -- neither exists anywhere in the
canonical schema (0001). This migration adds them as nullable, declared
onboarding metadata on `buildings`, following the exact precedent already set
by `declared_unoccupied_baseline`/`declared_occupancy_schedule` in 0001: owner-
declared, optional, defaulting to a documented static fallback in
shared/config/optimization.py when absent -- not a required field, not a
separate table, matching how occupancy is already modeled.

Also adds `model_quality_incidents`, a distinct table from the existing
`data_quality_alerts` (0004): TRD v2.0 §4's bounds-enforcement invariant
("an out-of-bounds result is rejected at the service layer and logged as a
model-quality incident, not silently clipped") describes a different failure
class (an optimization scenario's own output failing plausibility bounds)
than a data-quality alert (bad sensor/ingestion data), so it is not reused --
same RLS-protected, tenant-scoped shape as data_quality_alerts, kept
semantically separate on purpose.

Adds:
  - buildings.declared_tariff_schedule JSONB (nullable)
  - buildings.declared_rooftop_area_sqm DOUBLE PRECISION (nullable)
  - buildings.latitude / buildings.longitude DOUBLE PRECISION (nullable)
  - model_quality_incidents table (RLS + tenant_isolation policy + grants)

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE buildings ADD COLUMN declared_tariff_schedule JSONB")
    op.execute("ALTER TABLE buildings ADD COLUMN declared_rooftop_area_sqm DOUBLE PRECISION")
    op.execute("ALTER TABLE buildings ADD COLUMN latitude DOUBLE PRECISION")
    op.execute("ALTER TABLE buildings ADD COLUMN longitude DOUBLE PRECISION")

    op.execute("""
        CREATE TABLE model_quality_incidents (
            incident_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,
            building_id UUID NOT NULL,
            scenario_model TEXT NOT NULL,
            incident_type TEXT NOT NULL,
            severity TEXT NOT NULL DEFAULT 'warning',
            message TEXT NOT NULL,
            metadata JSONB,
            acknowledged BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("ALTER TABLE model_quality_incidents ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON model_quality_incidents "
        "USING (tenant_id = current_setting('app.current_tenant_id')::uuid)"
    )
    op.execute("ALTER TABLE model_quality_incidents FORCE ROW LEVEL SECURITY")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON model_quality_incidents TO carbonsense_app")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS model_quality_incidents CASCADE")
    op.execute("ALTER TABLE buildings DROP COLUMN IF EXISTS declared_tariff_schedule")
    op.execute("ALTER TABLE buildings DROP COLUMN IF EXISTS declared_rooftop_area_sqm")
    op.execute("ALTER TABLE buildings DROP COLUMN IF EXISTS latitude")
    op.execute("ALTER TABLE buildings DROP COLUMN IF EXISTS longitude")
