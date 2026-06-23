# CarbonSense — Celery+Redis Fallback Spike

**Version:** 1.0
**Status:** Reference — deliberate, reversible downgrade option
**Source:** TRD v2.0 §1.2, ROADMAP ENG-2e
**Decision:** Temporal Cloud remains the primary orchestrator. This document records the fallback path.

---

## Context

TRD v2.0 §1.2 specifies Temporal as the workflow orchestrator but explicitly names Celery+Redis as a documented fallback:

> "If even the managed offering proves too heavy before product-market fit, fall back to Celery + Redis for the linear pipeline steps, accepting that human-in-the-loop waits and resumable-from-failure semantics must be hand-built on top — a real cost, not a free substitution."

This spike documents what a Celery-based linear pipeline would look like, and what capabilities are lost.

---

## Linear-Step Celery Concept

### Stack

- `celery >= 5.4` — task queue
- `redis >= 5.0` — broker + result backend

### Pipeline as a Celery Chain

```python
from celery import chain

analysis_pipeline = chain(
    data_quality_gate.s(tenant_id, building_id),
    group(
        rule_engine.s(),
        stl_detection.s(),
    ),
    feature_assembly.s(),
    ml_ensemble.s(),
    confidence_calibration.s(),
    root_cause_attribution.s(),
)

result = analysis_pipeline.apply_async()
```

Each step is a Celery `@task` that receives the previous step's output. The `group()` primitive runs Rule Engine and STL Detection in parallel.

### Scheduled Jobs

Celery Beat handles cron scheduling:

```python
# celeryconfig.py
beat_schedule = {
    "drift-detection-nightly": {
        "task": "tasks.drift_detection",
        "schedule": crontab(hour=2, minute=0),
    },
    "retraining-monthly": {
        "task": "tasks.retraining",
        "schedule": crontab(day_of_month=1, hour=3),
    },
}
```

---

## What Is Lost Compared to Temporal

| Capability | Temporal | Celery+Redis | Impact |
|---|---|---|---|
| **Workflow durability** | Built-in. Workflow state persisted by Temporal server. Worker crash = automatic resume from last checkpoint. | Not built-in. Task retries exist but the *chain state* is not persisted. A broker crash or worker death mid-chain loses the pipeline's position. Must hand-build checkpoint tables. | **High.** The analysis pipeline is 7+ sequential/parallel steps. Losing position mid-pipeline means re-running from scratch or building a custom state machine. |
| **Replay** | Built-in. Any workflow execution can be replayed from its event history for debugging and auditing. | Not available. Task results exist in the result backend but there is no replay mechanism — you cannot "re-run the same chain with the same inputs and verify it produces the same outputs" without custom tooling. | **High** for audit-defensibility (PRD §6). |
| **Human-in-the-loop signals** | First-class. `workflow.wait_condition()` + `@workflow.signal` pause the workflow durably. No resources consumed while waiting. Survives worker restarts. | Must be hand-built. Options: (a) a polling task that checks a database flag, (b) a webhook that re-enqueues the next step. Both require custom code and are fragile across restarts. | **High.** The Feedback Loop (TRD §3.8) means workflows can wait days for a facility manager's response. |
| **Queryable execution state** | Built-in. `@workflow.query` returns current state without modifying it. Dashboard can poll "what step is this pipeline on?" | Must be hand-built. Requires writing step progress to a database table and querying it separately. | **Medium.** Useful for operator dashboards but not a correctness requirement. |
| **Deterministic execution** | Enforced by the SDK. Workflows are replayed from history; non-deterministic operations fail replay, catching bugs early. | Not enforced. Tasks are fire-and-forget functions. No determinism guarantee means subtle bugs from non-deterministic retries. | **Medium.** Matters more as pipeline complexity grows. |
| **Cron workflow visibility** | Same dashboard as request-path workflows. Replay, history, and debugging tools apply equally. | Celery Beat + Flower (monitoring). Separate tooling from the request-path task queue. No replay capability. | **Low.** Operationally inconvenient but not blocking. |
| **Multi-tenant workflow isolation** | Workflow ID includes tenant_id. Each tenant's workflows are independently observable and manageable. | Task arguments include tenant_id but there is no built-in namespace isolation. Must filter by task metadata in monitoring tools. | **Low** at current scale, **medium** at multi-tenant production scale. |

---

## Recommendation

**Do not switch to Celery unless Temporal Cloud's cost or operational overhead becomes a concrete, measured blocker — not a hypothetical concern.**

The capabilities lost (durability, replay, signals, deterministic execution) are not cosmetic — they are the specific properties that make the analysis pipeline reliable for a multi-tenant SaaS platform where a single pipeline run can span hours (human-in-the-loop) and must survive infrastructure failures transparently.

If a switch becomes necessary:

1. Implement a `pipeline_state` database table to track step completion per workflow run.
2. Implement a polling-based feedback wait (a Celery task that checks `feedback_labels` every N minutes and re-enqueues the next step when feedback arrives).
3. Accept that replay and deterministic execution are lost — auditing will require application-level logging, not infrastructure-level replay.
4. Keep the Temporal implementation intact in the codebase behind a feature flag, so the switch is genuinely reversible.

---

*This document satisfies ENG-2e: "Design doc + spike branch proves linear-step feasibility; documented as a deliberate, reversible downgrade, not silently decided."*
