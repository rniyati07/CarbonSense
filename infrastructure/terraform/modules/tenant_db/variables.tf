variable "tenant_id" {
  description = "Unique tenant identifier"
  type        = string
}

variable "isolation_tier" {
  description = "Isolation posture: shared_rls, dedicated_schema, or dedicated_db"
  type        = string

  validation {
    condition     = contains(["shared_rls", "dedicated_schema", "dedicated_db"], var.isolation_tier)
    error_message = "isolation_tier must be one of: shared_rls, dedicated_schema, dedicated_db"
  }
}

variable "shared_database_name" {
  description = "Database name for shared-RLS tenants"
  type        = string
}

variable "db_admin_user" {
  description = "Admin user for provisioning"
  type        = string
}

variable "db_admin_password" {
  description = "Admin user password"
  type        = string
  sensitive   = true
}

variable "db_host" {
  description = "PostgreSQL host"
  type        = string
}

variable "db_port" {
  description = "PostgreSQL port"
  type        = number
}

variable "app_role_name" {
  description = "Application role name"
  type        = string
}

variable "alembic_dir" {
  description = "Path to the directory containing alembic.ini"
  type        = string
}

variable "alembic_migrations_hash" {
  description = "Hash of the migrations directory — triggers re-provisioning when migrations change"
  type        = string
}