# CarbonSense — Root Terraform Configuration
#
# Provisions the shared database and per-tenant isolation resources.
# All tiers use Alembic as the single migration runner — no separate
# DDL file, no drift. See TRD v2.0 §2.1.

resource "postgresql_database" "shared" {
  name  = var.shared_database_name
  owner = var.db_admin_user
}

resource "postgresql_role" "app" {
  name     = var.app_role_name
  login    = true
  password = var.app_role_password
}

module "tenant" {
  source   = "./modules/tenant_db"
  for_each = var.tenants

  tenant_id      = each.key
  isolation_tier = each.value.isolation_tier

  shared_database_name    = var.shared_database_name
  db_admin_user           = var.db_admin_user
  db_admin_password       = var.db_admin_password
  db_host                 = var.db_host
  db_port                 = var.db_port
  app_role_name           = var.app_role_name
  alembic_dir             = var.alembic_dir
  alembic_migrations_hash = var.alembic_migrations_hash
}