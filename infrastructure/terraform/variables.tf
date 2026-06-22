variable "db_host" {
  description = "PostgreSQL host"
  type        = string
  default     = "localhost"
}

variable "db_port" {
  description = "PostgreSQL port"
  type        = number
  default     = 5432
}

variable "db_admin_user" {
  description = "Admin user for database provisioning"
  type        = string
  default     = "postgres"
}

variable "db_admin_password" {
  description = "Admin user password"
  type        = string
  sensitive   = true
}

variable "db_sslmode" {
  description = "SSL mode for database connections"
  type        = string
  default     = "prefer"
}

variable "shared_database_name" {
  description = "Database name for shared-RLS tenants"
  type        = string
  default     = "carbonsense"
}

variable "app_role_name" {
  description = "Application role name (non-superuser)"
  type        = string
  default     = "carbonsense_app"
}

variable "app_role_password" {
  description = "Application role password"
  type        = string
  sensitive   = true
}

variable "alembic_dir" {
  description = "Path to the directory containing alembic.ini"
  type        = string
  default     = "../../database"
}

variable "alembic_migrations_hash" {
  description = "Hash of the migrations directory — triggers re-provisioning when migrations change. Compute externally, e.g.: sha256sum database/migrations/versions/*.py"
  type        = string
  default     = ""
}

variable "tenants" {
  description = "Map of tenant configurations to provision"
  type = map(object({
    isolation_tier = string # shared_rls | dedicated_schema | dedicated_db
  }))
  default = {}
}