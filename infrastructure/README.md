# infrastructure/

Infrastructure provisioning, containerization, orchestration, and monitoring configuration.

## Subfolders

| Folder | Purpose | Epic |
|---|---|---|
| `terraform/` | Infrastructure-as-code — hybrid isolation provisioning (shared-RLS + dedicated-schema/DB tiers), TimescaleDB, Kafka, S3, Temporal Cloud | **ENG-1c** |
| `docker/` | Dockerfiles and docker-compose for local development and CI | **ENG-1c** |
| `kubernetes/` | Kubernetes manifests for production deployment | **ENG-1c** |
| `monitoring/` | Prometheus/Grafana dashboards, alerting rules, OpenTelemetry collector config | **ENG-7a, ENG-7b** |

## Rules

1. Terraform is the source of truth for infrastructure.
2. One Terraform module provisions both isolation postures (shared-RLS and dedicated-schema); only the `search_path`/connection target differs.
3. Monitoring must alert on: drift rate, FP-rate approaching ceiling, latency SLO breaches, and webhook delivery failures.