output "database_name" {
  description = "Database to connect to for this tenant"
  value       = local.db_name
}

output "schema_name" {
  description = "Schema name for this tenant"
  value       = local.schema_name
}

output "search_path" {
  description = "PostgreSQL search_path to set for this tenant's connections"
  value       = local.schema_name
}

output "isolation_tier" {
  description = "The isolation tier provisioned for this tenant"
  value       = var.isolation_tier
}