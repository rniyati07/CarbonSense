# apps/

Application entry points for CarbonSense.

## Subfolders

| Folder | Purpose | Epic |
|---|---|---|
| `api/` | FastAPI API Gateway and public APIs — TLS termination, auth, tenant-scoped rate limiting, request routing | **ENG-5** |
| `worker/` | Temporal workers and scheduled jobs — analysis pipeline workers, cron workflow runners | **ENG-2** |
| `admin/` | Internal admin utilities — tenant provisioning, maintenance tooling | — |

## Rules

- All client surfaces (dashboard, integrator, future mobile) call the same API (`api/`).
- Workers are stateless Temporal activity/workflow runners, not standalone services.
- No business logic lives here — delegate to `services/` and `shared/`.