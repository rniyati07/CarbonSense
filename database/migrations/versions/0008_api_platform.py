"""ENG-5: API & Integrator Platform — schema additions.

TRD v2.0 §7 requires infrastructure that has no home in the schema through
0007: OAuth2 client-credentials issuance (§7.2) needs somewhere to store
client_id/client_secret_hash pairs (also serves as the "API key management"
half of the Tenant/Admin API, §7.1 — one mechanism, not two); async result
delivery (§7.3) needs webhook registrations and a per-(tenant, key) record
for Idempotency-Key replay detection; the Ingestion API (§7.1) needs a
queryable "ingestion batch status" record, since a CSV upload's downstream
quality-gate result is otherwise only ever a transient in-memory
BatchQualityResult; and partner sandboxing (§7.4) needs a way to mark a
tenant's isolation_tier row as sandbox-only (synthetic data, no production
access) rather than inventing a parallel tenant concept.

idempotency_keys, webhook_registrations, and ingestion_batches are only ever
queried inside an already-authenticated, tenant-scoped request and get the
identical tenant_isolation RLS policy already established by 0002/0007.

api_clients is the deliberate exception: the OAuth2 token endpoint must look
up a row by client_id alone, before any tenant context exists to satisfy an
RLS predicate -- the same chicken-and-egg problem the `tenants` table itself
already has, which is why `tenants` was never added to 0002's RLS list
either. api_clients follows that exact precedent (no RLS policy); every
application-level query against it still filters by tenant_id explicitly in
the repository, and the only value it exposes pre-auth is a salted secret
hash, never a plaintext credential.

analysis_jobs backs the Scenario API's portfolio-analyze endpoint
(§7.3's own literal example, POST /v1/scenarios/analyze). This is a
deliberately different async mechanism than AnalysisPipelineWorkflow's
Temporal orchestration: a portfolio scenario rollup is in-process LP-solve
work over already-persisted findings (seconds, not the multi-stage,
human-review-gated pipeline run Temporal exists for) -- FastAPI
BackgroundTasks plus this status row is proportionate, not a second
orchestration engine competing with Temporal.

ingestion_webhooks is the inbound counterpart to webhook_registrations:
where webhook_registrations is a URL *CarbonSense calls* on job completion,
ingestion_webhooks is a receiver credential *CarbonSense exposes* for a
smart-meter provider to push readings into (TRD v2.0 §7.1's "smart-meter
API webhook registration"). Provider-specific auth/format is explicitly a
BD decision out of TRD scope (Appendix B, OQ-4) -- this table only owns
the generic receiver-credential half every provider integration needs
regardless of which provider it is. It carries the same pre-auth lookup
requirement as api_clients (the receiver endpoint identifies the
tenant/building from webhook_id alone, verified against
receiver_secret_hash, before any tenant context exists) and so gets the
same no-RLS treatment for the same reason.

Adds:
  - api_clients (OAuth2 client-credentials store, no RLS -- see above)
  - idempotency_keys (Idempotency-Key replay cache)
  - webhook_registrations (per-tenant HMAC-signed outbound callback URLs)
  - ingestion_webhooks (per-building inbound smart-meter push receivers, no RLS)
  - ingestion_batches (queryable batch status for the 202+poll pattern)
  - analysis_jobs (queryable status for portfolio scenario analysis)
  - tenants.is_sandbox BOOLEAN (partner sandbox marker)

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_TENANT_SCOPED_TABLES: list[str] = [
    "idempotency_keys",
    "webhook_registrations",
    "ingestion_batches",
    "analysis_jobs",
]


def _apply_tenant_isolation_policy(table: str) -> None:
    op.execute(f"""
        CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = current_setting('app.current_tenant_id')::uuid)
    """)
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO carbonsense_app")


def upgrade() -> None:
    op.execute("ALTER TABLE tenants ADD COLUMN is_sandbox BOOLEAN NOT NULL DEFAULT FALSE")

    op.execute("""
        CREATE TABLE api_clients (
            client_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(tenant_id),
            client_secret_hash TEXT NOT NULL,
            name TEXT NOT NULL,
            tier TEXT NOT NULL DEFAULT 'freemium'
                CHECK (tier IN ('freemium', 'paid_sme', 'enterprise', 'integrator')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            revoked_at TIMESTAMPTZ
        )
    """)
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON api_clients TO carbonsense_app")

    op.execute("""
        CREATE TABLE idempotency_keys (
            tenant_id UUID NOT NULL,
            idempotency_key TEXT NOT NULL,
            endpoint TEXT NOT NULL,
            response_status INTEGER NOT NULL,
            response_body JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, idempotency_key, endpoint)
        )
    """)
    op.execute("ALTER TABLE idempotency_keys ENABLE ROW LEVEL SECURITY")

    op.execute("""
        CREATE TABLE webhook_registrations (
            webhook_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(tenant_id),
            url TEXT NOT NULL,
            hmac_secret TEXT NOT NULL,
            event_types TEXT[] NOT NULL DEFAULT ARRAY['analysis.completed'],
            active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("ALTER TABLE webhook_registrations ENABLE ROW LEVEL SECURITY")

    op.execute("""
        CREATE TABLE ingestion_webhooks (
            webhook_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(tenant_id),
            building_id UUID NOT NULL REFERENCES buildings(building_id),
            provider TEXT NOT NULL,
            receiver_secret_hash TEXT NOT NULL,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ingestion_webhooks TO carbonsense_app")

    op.execute("""
        CREATE TABLE ingestion_batches (
            batch_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(tenant_id),
            building_id UUID NOT NULL REFERENCES buildings(building_id),
            status TEXT NOT NULL DEFAULT 'processing'
                CHECK (status IN ('processing', 'pass', 'degraded', 'quarantined', 'failed')),
            total_rows INTEGER NOT NULL DEFAULT 0,
            pass_count INTEGER NOT NULL DEFAULT 0,
            degraded_count INTEGER NOT NULL DEFAULT 0,
            quarantined_count INTEGER NOT NULL DEFAULT 0,
            ingestion_source TEXT,
            correlation_id UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("ALTER TABLE ingestion_batches ENABLE ROW LEVEL SECURITY")

    op.execute("""
        CREATE TABLE analysis_jobs (
            job_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(tenant_id),
            job_type TEXT NOT NULL DEFAULT 'portfolio_scenario',
            status TEXT NOT NULL DEFAULT 'processing'
                CHECK (status IN ('processing', 'completed', 'failed')),
            building_ids JSONB NOT NULL,
            result JSONB,
            error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            completed_at TIMESTAMPTZ
        )
    """)
    op.execute("ALTER TABLE analysis_jobs ENABLE ROW LEVEL SECURITY")

    for table in _NEW_TENANT_SCOPED_TABLES:
        _apply_tenant_isolation_policy(table)


def downgrade() -> None:
    for table in _NEW_TENANT_SCOPED_TABLES:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")

    op.execute("DROP TABLE IF EXISTS ingestion_webhooks CASCADE")
    op.execute("DROP TABLE IF EXISTS api_clients CASCADE")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS is_sandbox")
