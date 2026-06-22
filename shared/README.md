# shared/

Cross-cutting utilities and infrastructure shared across all services and apps.

## Subfolders

| Folder | Purpose | Epic |
|---|---|---|
| `auth/` | Authentication and authorization — OAuth2, JWT validation, tenant-scoping from token claims | **ENG-5a, ENG-5c** |
| `config/` | Configuration management — environment variable loading, settings models | — |
| `logging/` | Structured logging setup with trace ID propagation | **ENG-7a** |
| `observability/` | OpenTelemetry instrumentation, distributed tracing, metrics export | **ENG-7a, ENG-7b** |
| `exceptions/` | Shared exception hierarchy — tenant isolation errors, validation errors, model serving errors | — |
| `utils/` | General-purpose utilities — date/time helpers, data validation, common patterns | — |

## Rules

1. Shared utilities belong in `shared/`, never duplicated across services.
2. Tenant scoping uses the validated token claim, never a client-supplied header alone.
3. Every request must propagate a trace ID across service boundaries and Temporal workflow executions.