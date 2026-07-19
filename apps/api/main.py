"""ENG-5 — API & Integrator Platform: the FastAPI gateway app factory.

TRD v2.0 §7: "the dashboard, an integrator (PRD §4.3), and any future
client all consume the identical surface." This module wires that surface
together -- routing, auth, exception mapping -- but contains no business
logic itself; every router is a thin wrapper over an existing service
(OptimizationService, ReportService, FeedbackService, DomainRuleEngine's
Finding model, TenantAdminService), per the "no ML/business logic in
apps/api" constraint.

Path versioning (TRD v2.0 §7.2 "Path-versioned (/v1/...)"): every route is
declared under /v1 directly in its router (not via FastAPI's `prefix=`
mounted here), so a future /v2 app can be built by mounting a disjoint set
of /v2 routers into the same app rather than restructuring this factory.
"""

from __future__ import annotations

from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from apps.api.errors import register_exception_handlers
from apps.api.routers import (
    feedback,
    findings,
    ingestion,
    oauth,
    reports,
    scenarios,
    tenant,
)

API_TITLE = "CarbonSense API"
API_VERSION = "1.0.0"

# ENG-5c: "a deprecation policy... documented in the public API reference,
# not just internally" (TRD v2.0 §7.2). FastAPI renders `description` as
# the top-level markdown body of the generated /docs (Swagger UI) and
# /redoc pages, which *is* the public API reference -- so the policy lives
# here, not in a repo-internal doc a caller would never see.
API_DESCRIPTION = """\
CarbonSense integrator-facing API (TRD v2.0 §7). The dashboard, integrator \
clients, and any future consumer all use this identical surface.

## Versioning and Deprecation

- All endpoints are path-versioned under `/v1/...`.
- A new major version (`/v2/...`) is introduced additively, alongside `/v1`,
  never by breaking it in place.
- Once `/v2` is available, `/v1` enters a **minimum 6-month deprecation
  window** before retirement. Deprecation is announced here, in this
  reference, at the start of that window -- not only through direct
  integrator notification.
- Breaking changes are never shipped under an existing version path; a
  breaking change is definitionally what triggers the next version.
"""


def create_app() -> FastAPI:
    app = FastAPI(title=API_TITLE, version=API_VERSION, description=API_DESCRIPTION)

    register_exception_handlers(app)

    app.include_router(oauth.router)
    app.include_router(findings.router)
    app.include_router(feedback.router)
    app.include_router(scenarios.router)
    app.include_router(reports.router)
    app.include_router(ingestion.router)
    app.include_router(tenant.router)

    @app.get("/healthz", tags=["health"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    FastAPIInstrumentor.instrument_app(app)
    return app


app = create_app()
