output "shared_database_name" {
  description = "Shared database name for shared_rls tenants"
  value       = postgresql_database.shared.name
}

output "app_role_name" {
  description = "Application role name"
  value       = postgresql_role.app.name
}

output "tenant_connections" {
  description = "Per-tenant connection configuration"
  value = {
    for tenant_id, mod in module.tenant : tenant_id => {
      database    = mod.database_name
      schema      = mod.schema_name
      search_path = mod.search_path
    }
  }
}