# CarbonSense — Tenant Database Provisioning Module
#
# Provisions all isolation postures using Alembic as the single migration
# runner — eliminating DDL drift between tiers. See TRD v2.0 §2.1:
# "One schema definition, two isolation postures."
#
# Tiers:
#   shared_rls       — Shared tables in the public schema. Alembic runs
#                      against the shared database during normal deploys.
#                      No per-tenant provisioner needed.
#   dedicated_schema — Per-tenant schema in the shared database. Alembic
#                      runs with ALEMBIC_SCHEMA=tenant_{id} so identical
#                      migrations land in the tenant's schema.
#   dedicated_db     — Per-tenant database. Alembic runs with DATABASE_URL
#                      pointed at the new database.

locals {
  safe_id = replace(var.tenant_id, "-", "_")

  is_shared           = var.isolation_tier == "shared_rls"
  is_dedicated_schema = var.isolation_tier == "dedicated_schema"
  is_dedicated_db     = var.isolation_tier == "dedicated_db"

  schema_name = local.is_dedicated_schema ? "tenant_${local.safe_id}" : "public"
  db_name     = local.is_dedicated_db ? "carbonsense_${local.safe_id}" : var.shared_database_name

  # Connection URL for Alembic — points at the correct database per tier.
  alembic_db_url = "postgresql://${var.db_admin_user}:${var.db_admin_password}@${var.db_host}:${var.db_port}/${local.db_name}"
}

# ── dedicated_db: create a separate database ──────────────────────

resource "postgresql_database" "tenant" {
  count = local.is_dedicated_db ? 1 : 0
  name  = local.db_name
  owner = var.db_admin_user
}

# ── dedicated_schema: create a schema in the shared database ──────

resource "postgresql_schema" "tenant" {
  count    = local.is_dedicated_schema ? 1 : 0
  name     = local.schema_name
  database = var.shared_database_name
  owner    = var.db_admin_user
}

# ── Grant app role access to the tenant's schema ──────────────────

resource "postgresql_grant" "schema_usage" {
  count       = local.is_dedicated_schema ? 1 : 0
  database    = var.shared_database_name
  role        = var.app_role_name
  schema      = local.schema_name
  object_type = "schema"
  privileges  = ["USAGE", "CREATE"]
}

# ── Run Alembic migrations against the target ─────────────────────
#
# For shared_rls: Alembic runs during normal deploy against the shared
# database. No per-tenant provisioner needed.
#
# For dedicated_schema: Alembic runs with ALEMBIC_SCHEMA set so
# migrations land in the tenant's schema. version_table is also
# scoped to the schema so each tenant tracks its own migration state.
#
# For dedicated_db: Alembic runs with DATABASE_URL pointed at the
# new database.
#
# In both cases the IDENTICAL migration chain (0001–000N) is applied,
# guaranteeing schema parity with the shared-RLS tier — including
# RLS policies, FORCE ROW LEVEL SECURITY, and stored functions.

resource "null_resource" "run_alembic" {
  count = local.is_shared ? 0 : 1

  triggers = {
    tenant_id      = var.tenant_id
    isolation_tier = var.isolation_tier
    alembic_hash   = var.alembic_migrations_hash
  }

  provisioner "local-exec" {
    working_dir = var.alembic_dir
    environment = {
      DATABASE_URL   = local.alembic_db_url
      ALEMBIC_SCHEMA = local.is_dedicated_schema ? local.schema_name : ""
    }
    command = "alembic upgrade head"
  }

  depends_on = [
    postgresql_database.tenant,
    postgresql_schema.tenant,
  ]
}