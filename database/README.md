# database/

Database schema, migrations, seed data, and security policies.

CarbonSense uses TimescaleDB (Postgres + Timescale extension) as its unified relational
and time-series store, with Row-Level Security (RLS) enforcing multi-tenant isolation
at the database layer.

## Subfolders

| Folder | Purpose | Epic |
|---|---|---|
| `migrations/` | Alembic migrations — all schema changes go through here | **ENG-1a** |
| `seeds/` | Seed data for development and testing (golden COMBED fixture, synthetic tenants) | **ENG-1a** |
| `ddl/` | Canonical DDL definitions (tenants, buildings, submeter_circuits, normalized_readings, findings, feedback_labels, audit_log) | **ENG-1a** |
| `policies/` | Row-Level Security policies — tenant isolation enforced at the DB layer, not app logic | **ENG-1b** |

## Rules

1. All database schema changes must go through `migrations/`.
2. RLS is mandatory on every tenant-scoped table.
3. `audit_log` is append-only — no UPDATE/DELETE grants for the application role.
4. The application sets `app.current_tenant_id` from the authenticated token's tenant claim, never from a client-supplied header alone.