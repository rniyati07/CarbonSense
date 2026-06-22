# orchestration/

Workflow orchestration (Temporal) and event backbone (Kafka) definitions.

Temporal is the workflow orchestrator for the analysis pipeline and scheduled ML jobs.
Kafka sits upstream — ingestion services publish events; lightweight consumers start
corresponding Temporal workflow executions.

## Subfolders

| Folder | Purpose | Epic |
|---|---|---|
| `temporal/workflows/` | Temporal workflow definitions — analysis pipeline, retraining, drift detection | **ENG-2c, ENG-2d** |
| `temporal/activities/` | Temporal activity implementations — individual layer invocations, model serving calls | **ENG-2c** |
| `temporal/schedules/` | Temporal cron schedule definitions — nightly drift detection, periodic retraining | **ENG-2d** |
| `events/kafka/` | Kafka topic definitions, event schemas (`building.data.arrived`, `finding.confirmed`, `model.promoted`, `model.drift.detected`) | **ENG-2b** |

## Rules

1. Temporal workflows live only under `orchestration/temporal/`.
2. Workflows are parameterized with `tenant_id` — never pooled across tenants.
3. The event backbone decouples ingestion from analysis — a burst of uploads doesn't block on pipeline capacity.