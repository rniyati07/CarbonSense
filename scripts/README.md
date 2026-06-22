# scripts/

Operational scripts for bootstrapping, migrations, and maintenance.

## Subfolders

| Folder | Purpose |
|---|---|
| `bootstrap/` | Environment setup scripts — database initialization, Kafka topic creation, Temporal namespace provisioning |
| `migrations/` | Database migration helpers — Alembic wrappers, data backfill scripts |
| `maintenance/` | Operational maintenance — tenant provisioning, audit log rotation, model artifact cleanup |