"""ENG-1e: Retention policy enforcement + deletion cascade functions.

Creates PL/pgSQL functions for controlled tenant data deletion:

  - delete_building_data(tenant_id, building_id): Cascades deletes through
    feedback_labels -> findings -> normalized_readings -> building_calendar
    -> submeter_circuits -> buildings. NEVER touches audit_log.

  - delete_tenant_data(tenant_id): Deletes all buildings for a tenant
    by calling delete_building_data for each, then removes the tenant row.

Both functions write the deletion event to audit_log BEFORE any cascade,
satisfying TRD v2.0 §2.5: "a deletion event is itself logged, not a
literal erasure of audit history."

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── delete_building_data ──────────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION delete_building_data(
            p_tenant_id UUID,
            p_building_id UUID
        ) RETURNS void AS $$
        DECLARE
            v_building_name TEXT;
            v_circuits_deleted BIGINT;
            v_readings_deleted BIGINT;
            v_findings_deleted BIGINT;
            v_feedback_deleted BIGINT;
            v_calendar_deleted BIGINT;
        BEGIN
            -- Verify the building belongs to this tenant
            SELECT name INTO v_building_name
            FROM buildings
            WHERE building_id = p_building_id
              AND tenant_id = p_tenant_id;

            IF v_building_name IS NULL THEN
                RAISE EXCEPTION 'Building % not found for tenant %',
                    p_building_id, p_tenant_id;
            END IF;

            -- 1. Log the deletion event to audit_log FIRST
            INSERT INTO audit_log (tenant_id, event_type, entity_id, payload)
            VALUES (
                p_tenant_id,
                'building.data.deleted',
                p_building_id,
                jsonb_build_object(
                    'building_name', v_building_name,
                    'building_id', p_building_id,
                    'tenant_id', p_tenant_id,
                    'initiated_at', now()
                )
            );

            -- 2. Cascade deletes in FK-safe order (leaf to root)

            -- feedback_labels (depends on findings)
            DELETE FROM feedback_labels
            WHERE finding_id IN (
                SELECT finding_id FROM findings
                WHERE building_id = p_building_id
                  AND tenant_id = p_tenant_id
            );
            GET DIAGNOSTICS v_feedback_deleted = ROW_COUNT;

            -- findings
            DELETE FROM findings
            WHERE building_id = p_building_id
              AND tenant_id = p_tenant_id;
            GET DIAGNOSTICS v_findings_deleted = ROW_COUNT;

            -- normalized_readings (depends on submeter_circuits)
            DELETE FROM normalized_readings
            WHERE circuit_id IN (
                SELECT circuit_id FROM submeter_circuits
                WHERE building_id = p_building_id
                  AND tenant_id = p_tenant_id
            )
              AND tenant_id = p_tenant_id;
            GET DIAGNOSTICS v_readings_deleted = ROW_COUNT;

            -- building_calendar
            DELETE FROM building_calendar
            WHERE building_id = p_building_id
              AND tenant_id = p_tenant_id;
            GET DIAGNOSTICS v_calendar_deleted = ROW_COUNT;

            -- submeter_circuits (self-referencing: delete children first)
            -- Delete in a loop to handle arbitrary nesting depth
            LOOP
                DELETE FROM submeter_circuits
                WHERE building_id = p_building_id
                  AND tenant_id = p_tenant_id
                  AND circuit_id NOT IN (
                      SELECT parent_circuit_id FROM submeter_circuits
                      WHERE parent_circuit_id IS NOT NULL
                        AND building_id = p_building_id
                        AND tenant_id = p_tenant_id
                  );
                GET DIAGNOSTICS v_circuits_deleted = ROW_COUNT;
                EXIT WHEN v_circuits_deleted = 0;
            END LOOP;

            -- building itself
            DELETE FROM buildings
            WHERE building_id = p_building_id
              AND tenant_id = p_tenant_id;

            -- 3. Log completion to audit_log
            INSERT INTO audit_log (tenant_id, event_type, entity_id, payload)
            VALUES (
                p_tenant_id,
                'building.data.deletion_completed',
                p_building_id,
                jsonb_build_object(
                    'building_name', v_building_name,
                    'feedback_deleted', v_feedback_deleted,
                    'findings_deleted', v_findings_deleted,
                    'readings_deleted', v_readings_deleted,
                    'calendar_deleted', v_calendar_deleted,
                    'completed_at', now()
                )
            );
        END;
        $$ LANGUAGE plpgsql
    """)

    # ── delete_tenant_data ────────────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION delete_tenant_data(
            p_tenant_id UUID
        ) RETURNS void AS $$
        DECLARE
            v_building RECORD;
            v_tenant_name TEXT;
        BEGIN
            -- Verify tenant exists
            SELECT name INTO v_tenant_name
            FROM tenants
            WHERE tenant_id = p_tenant_id;

            IF v_tenant_name IS NULL THEN
                RAISE EXCEPTION 'Tenant % not found', p_tenant_id;
            END IF;

            -- Log tenant deletion initiation
            INSERT INTO audit_log (tenant_id, event_type, entity_id, payload)
            VALUES (
                p_tenant_id,
                'tenant.data.deletion_initiated',
                p_tenant_id,
                jsonb_build_object(
                    'tenant_name', v_tenant_name,
                    'initiated_at', now()
                )
            );

            -- Delete all buildings (each call cascades properly)
            FOR v_building IN
                SELECT building_id FROM buildings
                WHERE tenant_id = p_tenant_id
            LOOP
                PERFORM delete_building_data(p_tenant_id, v_building.building_id);
            END LOOP;

            -- Delete the tenant row itself
            DELETE FROM tenants WHERE tenant_id = p_tenant_id;

            -- Log completion (tenant_id still valid in audit_log since
            -- audit_log rows are NEVER deleted)
            INSERT INTO audit_log (tenant_id, event_type, entity_id, payload)
            VALUES (
                p_tenant_id,
                'tenant.data.deletion_completed',
                p_tenant_id,
                jsonb_build_object(
                    'tenant_name', v_tenant_name,
                    'completed_at', now()
                )
            );
        END;
        $$ LANGUAGE plpgsql
    """)

    # Grant execute to the app role
    op.execute("GRANT EXECUTE ON FUNCTION delete_building_data(UUID, UUID) TO carbonsense_app")
    op.execute("GRANT EXECUTE ON FUNCTION delete_tenant_data(UUID) TO carbonsense_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS delete_tenant_data(UUID)")
    op.execute("DROP FUNCTION IF EXISTS delete_building_data(UUID, UUID)")
