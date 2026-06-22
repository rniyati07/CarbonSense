# CarbonSense — Engineering Roadmap

**Version:** 2.0
**Status:** Active
**Supersedes:** ROADMAP v1.0 (4-day hackathon sprint plan — see Appendix: Migration Map)
**Source of Truth:** PRD v2.0, TRD v2.0
**Document Owner:** Engineering (Director of Engineering)
**Tracks:** Track 1 — Engineering & Platform · Track 2 — Research & Publication · Track 3 — Pilot & Go-to-Market Validation

---

## Preamble

CarbonSense's hackathon MVP proved the core product loop end-to-end: raw meter data in, explainable waste findings and a counterfactual action plan out, validated against the COMBED instrumented-building dataset inside a single demo session. That MVP is the reason several pieces of this roadmap exist as "rebuild and harden" work rather than greenfield work — the Data Quality Gate's normalization logic, the Optimizer's `scipy.optimize` scenario math, and the NarratorAgent's structured-JSON LLM pattern are all sound engineering, carried forward as components rather than rewritten from scratch (see PRD v2.0 §5–§7 and TRD v2.0 throughout for exactly which pieces survive). What the hackathon MVP did not need, and does not have, is multi-tenancy, durable orchestration, a model lifecycle, an integrator-facing API, or a research methodology rigorous enough to submit for peer review — and building those is what the rest of this document plans.

This roadmap does not restart at "Day 1." It plans forward from a working single-building proof of concept toward two coupled, parallel destinations: a production multi-tenant SaaS platform (Track 1, feeding Track 3's pilot validation) and a publishable research contribution in graph-aware fault localization (Track 2). The two tracks share infrastructure deliberately — Track 2's baseline comparisons consume Track 1's production Rule Engine, STL Residual, and ML Ensemble layers directly rather than reimplementing them, and Track 1's Root-Cause Attribution layer is the eventual landing zone for Track 2's validated output (PRD v2.0 §7.5). Track 3 runs alongside both, because a production platform and a research paper are each validated by contact with something Track 1 alone cannot provide: a real pilot customer's real building.

The roadmap below is organized as parallel tracks of epics, not sequential phases, with sprint/quarter-scale estimates and a dependency graph instead of a single linear critical path. A short, explicit "Hackathon Origin" note appears wherever a v1 artifact is being reused, so the provenance of carried-forward work is traceable without resurrecting hackathon-specific framing as an active roadmap item.

---

## 1. Roadmap Structure & Conventions

This roadmap replaces v1's hour-by-hour, Day 1–4 hackathon structure with conventions appropriate to a continuously-shipped SaaS product and a parallel academic research effort.

**Time unit.** Estimates are given in **days or weeks** of focused work per role, organized into **2-week sprints** rolling up to **quarters**. There is no fixed multi-day build window and no single demo deadline; sprint and quarter boundaries are planning checkpoints, not hard cutoffs.

**Numbering.** Subtasks use **Track-Epic-ID** numbering instead of purely sequential phase letters:
- **ENG-*** — Track 1, Engineering & Platform (e.g., `ENG-3d-2`)
- **RES-*** — Track 2, Research & Publication (e.g., `RES-1b`)
- **GTM-*** — Track 3, Pilot & Go-to-Market Validation (e.g., `GTM-2a`)

The number after the prefix identifies the epic (e.g., `ENG-3` = Anomaly Intelligence Platform Build-Out); a letter identifies the subtask within that epic; where an epic has sub-epics (only ENG-3 does, for its eight pipeline layers), a second letter follows (e.g., `ENG-3d-2` = ML Ensemble sub-epic, subtask 2).

**Owners are roles, not names.** v1 assigned work to Member 1–4 because the hackathon team's composition was fixed and known in advance. The production team's actual composition is not yet fixed, so every subtask is owned by a **role**: Backend Eng, ML Eng, Data Eng, Platform/DevOps Eng, Frontend Eng, Research Eng, Security Eng, or Product. Staffing a role with a specific person is a hiring/allocation decision made against this roadmap, not a property of the roadmap itself.

**Priority is relative to each track's own milestone, not a single demo.** v1 had one 🔴 Critical Path because everything served one live demo. v2 has no single demo to protect; instead, every subtask is tagged:
- **MUST-HAVE** — required to clear that track's named milestone (Section 7).
- **SHOULD-HAVE** — materially improves the platform/research output but does not gate the milestone.
- **NICE-TO-HAVE** — valuable, deferrable without weakening the milestone's claim.

**Dependencies are a graph, not a chain.** v1's Phase 0 → 1 → 2 → 3 → 4 → 5 was a single linear sequence because one team built one pipeline for one demo. v2 has three tracks advancing concurrently with real cross-track dependencies (Section 6) — a subtask's "Depends On" column may point to a subtask in a different track.

---

## 2. Track 1 — Engineering & Platform

Track 1 rebuilds the production-relevant content of v1's Phases 0–4 as epics organized around platform capability (per PRD v2.0 §5's organizing principle), not around the four named agents or a build day. *Hackathon Origin: the agent names (SensorAgent, AnomalyAgent, OptimizerAgent, NarratorAgent) are dropped per PRD v2.0 §5; the underlying logic each agent contained is cited as reused inside the relevant epic below, not rewritten from scratch — see the Migration Map appendix for the full agent-by-agent disposition.*

### Epic ENG-1 — Multi-Tenant Data Architecture

Replaces v1's single SQLite store and the "load 2–3 golden CSVs" onboarding framing with a tenant-isolated canonical schema (TRD v2.0 §2).

| ID | Subtask | Owner | Est. | Depends On | Deliverable / DoD | Priority |
|---|---|---|---|---|---|---|
| ENG-1a | Implement canonical schema on TimescaleDB (`tenants`, `buildings`, `submeter_circuits`, `normalized_readings` hypertable, `findings`, `feedback_labels`, append-only `audit_log`) | Data Eng | 2 wks | — | Schema migrated; hypertable created; `audit_log` has no UPDATE/DELETE grants | MUST-HAVE |
| ENG-1b | Implement Postgres RLS policies on every tenant-scoped table + per-request `app.current_tenant_id` context | Backend Eng | 1.5 wks | ENG-1a | RLS enabled with no superuser-bypass role; isolation enforced at DB layer, not app logic | MUST-HAVE |
| ENG-1c | Build hybrid isolation provisioning (shared-RLS tier + dedicated-schema/dedicated-DB tier) as one Terraform module | Platform Eng | 2 wks | ENG-1a | Identical DDL provisions both isolation postures; only `search_path`/connection target differs | MUST-HAVE |
| ENG-1d | Build `building_calendar` table + holiday-API import + customer-uploaded closures | Backend Eng | 1 wk | ENG-1a | STL layer (ENG-3c) can query day-type classification per building | SHOULD-HAVE |
| ENG-1e | Implement tenant-configurable `retention_policy` field + deletion cascade (`buildings → … → feedback_labels`, never `audit_log`) | Backend Eng | 1 wk | ENG-1a, ENG-1b | Deletion request cascades correctly in staging; `audit_log` entries persist; deletion event itself is logged | MUST-HAVE |
| ENG-1f | Build tenant-isolation fuzzer (CI security test class) | Security/QA Eng | 1.5 wks | ENG-1b | Fuzzer attempts cross-tenant reads/writes (wrong `tenant_id`, forged token claim, misconfigured job param) and asserts every attempt fails closed; runs on every data-layer PR | MUST-HAVE |

### Epic ENG-2 — Orchestration & Workflow Engine

Replaces v1's frontend-driven sequencing (orchestration logic living inside the Streamlit app) with a durable, resumable backend orchestrator (TRD v2.0 §1.2).

| ID | Subtask | Owner | Est. | Depends On | Deliverable / DoD | Priority |
|---|---|---|---|---|---|---|
| ENG-2a | Stand up Temporal Cloud namespace + worker deployment | Platform Eng | 1 wk | — | A hello-world workflow executes durably and survives a worker restart | MUST-HAVE |
| ENG-2b | Stand up event backbone (Kafka / managed MSK or Confluent Cloud) + `building.data.arrived` topic | Platform Eng | 1 wk | — | Ingestion can publish; a test consumer receives the event | MUST-HAVE |
| ENG-2c | Implement Analysis Pipeline Workflow skeleton (orchestrates Layers 1–7, signal/query primitives for human-in-loop waits) | Backend Eng | 2 wks | ENG-2a, ENG-2b | Workflow runs end-to-end against a synthetic tenant with stubbed layer calls | MUST-HAVE |
| ENG-2d | Implement scheduled cron workflows (Drift Detection, Retraining) | Backend Eng | 1 wk | ENG-2a | Cron workflow is visible and replayable in the Temporal UI | MUST-HAVE |
| ENG-2e | Document and spike the Celery+Redis fallback path | Backend Eng | 1 wk | ENG-2c | Design doc + spike branch proves linear-step feasibility; documented as a deliberate, reversible downgrade, not silently decided | NICE-TO-HAVE |

### Epic ENG-3 — Anomaly Intelligence Platform Build-Out

The architectural centerpiece (TRD v2.0 §3). Eight sub-epics — the PRD's seven layers plus the Feedback Loop, which is specified here given how tightly it couples to the ML Ensemble's lifecycle.

**ENG-3a — Data Quality Gate**

| ID | Subtask | Owner | Est. | Depends On | Deliverable / DoD | Priority |
|---|---|---|---|---|---|---|
| ENG-3a-1 | Port v1 normalization logic (column-alias matching, tz alignment, outlier-guard, gap-handling) into a standalone service | Backend Eng | 1.5 wks | ENG-1a | Service emits `normalized_reading_v1` rows; *Hackathon Origin: logic reused verbatim, cited not redesigned (TRD v2.0 §3.1)* | MUST-HAVE |
| ENG-3a-2 | Implement stuck-at-value and dropout detection, calibrated per `circuit_type` | Backend Eng | 1 wk | ENG-3a-1 | Golden COMBED fixture's known sensor faults are correctly caught | MUST-HAVE |
| ENG-3a-3 | Implement versioned implausible-value bounds table + schema-drift fingerprinting | Backend Eng | 1 wk | ENG-3a-1 | Bounds table editable without redeploy; schema drift triggers `degraded` status + customer notice | SHOULD-HAVE |
| ENG-3a-4 | Wire Gate → event-backbone handoff on `pass`/`degraded` | Backend Eng | 0.5 wk | ENG-3a-1, ENG-2b | A `quarantined`-only batch correctly suppresses downstream analysis and raises a data-quality alert | MUST-HAVE |

**ENG-3b — Domain Rule Engine**

| ID | Subtask | Owner | Est. | Depends On | Deliverable / DoD | Priority |
|---|---|---|---|---|---|---|
| ENG-3b-1 | Build YAML rule DSL + Python rule-evaluation service + `rule_registry` table | Backend Eng | 1.5 wks | ENG-1a | A rule change ships via reviewed PR + version bump, independent of any model deploy | MUST-HAVE |
| ENG-3b-2 | Author initial ASHRAE-Guideline-36-style rule set (after-hours HVAC, weekend vampire load, scheduling violations) | Backend Eng + Product | 1 wk | ENG-3b-1 | ≥3 reviewed rules produce correct findings on the golden COMBED fixture | MUST-HAVE |
| ENG-3b-3 | Wire rule-fired findings to `findings` table + pass rule context to Root-Cause Attribution | Backend Eng | 0.5 wk | ENG-3b-2, ENG-1a | Rule citation appears in the Explainability Bundle for rule-originated findings | MUST-HAVE |

**ENG-3c — STL Residual Detection**

| ID | Subtask | Owner | Est. | Depends On | Deliverable / DoD | Priority |
|---|---|---|---|---|---|---|
| ENG-3c-1 | Implement STL decomposition service (`statsmodels`) with calendar-aware day-type conditioning | ML Eng | 1.5 wks | ENG-1d | Holiday/declared-closure days are not scored as anomalous low-consumption days | MUST-HAVE |
| ENG-3c-2 | Feed STL residual magnitude + day-type classification as engineered features downstream | ML Eng | 0.5 wk | ENG-3c-1 | `feature_set_v1` includes STL-derived fields | MUST-HAVE |

**ENG-3d — ML Ensemble (Isolation Forest + Windowed Autoencoder)**

| ID | Subtask | Owner | Est. | Depends On | Deliverable / DoD | Priority |
|---|---|---|---|---|---|---|
| ENG-3d-1 | Define and version `feature_set_v1` (rolling stats, STL residuals, calendar features, rule-fire indicators) | ML Eng | 1 wk | ENG-3c-2, ENG-3b-3 | Feature contract documented and versioned | MUST-HAVE |
| ENG-3d-2 | Train/serve Isolation Forest as a scheduled per-tenant/per-building Temporal workflow | ML Eng | 1.5 wks | ENG-2d, ENG-3d-1 | Model artifact logged to MLflow under the `{tenant_id}/{building_id}/{layer}/{version}` convention; *Hackathon Origin: Isolation Forest itself reused from v1, no longer "the" detector* | MUST-HAVE |
| ENG-3d-3 | Build windowed Autoencoder (Keras/PyTorch) training + serving | ML Eng | 2 wks | ENG-3d-1 | Reconstruction-error scores logged; blind-spot overlap with Isolation Forest measured as low on the golden fixture | MUST-HAVE |
| ENG-3d-4 | Build lightweight model-serving microservice (loads currently-promoted version per building from MLflow) | Backend Eng | 1.5 wks | ENG-3d-2, ENG-3d-3, ENG-6a | Serving latency meets the §9.1 target in TRD v2.0 | MUST-HAVE |

**ENG-3e — Drift Detection**

| ID | Subtask | Owner | Est. | Depends On | Deliverable / DoD | Priority |
|---|---|---|---|---|---|---|
| ENG-3e-1 | Implement Mann-Kendall trend test on rolling efficiency ratio | ML Eng | 1 wk | ENG-3d-2 | Scheduled nightly cron workflow runs per building, outside the request path | MUST-HAVE |
| ENG-3e-2 | Wire `drifting` status to customer-facing notice + `model.drift.detected` event | Backend Eng | 0.5 wk | ENG-3e-1, ENG-2b | Event is observed by the retraining-trigger consumer (ENG-6b) | MUST-HAVE |

**ENG-3f — Confidence Calibration (Conformal Prediction)**

| ID | Subtask | Owner | Est. | Depends On | Deliverable / DoD | Priority |
|---|---|---|---|---|---|---|
| ENG-3f-1 | Implement conformal-prediction wrapper (MAPIE or custom) over ML Ensemble, STL, and rule-fire context | ML Eng | 2 wks | ENG-3d-4, ENG-3b-3, ENG-3c-2 | Every candidate finding carries a calibrated confidence interval, not an arbitrary score | MUST-HAVE |
| ENG-3f-2 | Implement per-building rolling calibration set + minimum-sample threshold + cold-start wide-band default | ML Eng | 1 wk | ENG-3f-1, ENG-1a (`cold_start` flag) | Cold-start buildings surface an explicit "low confidence — still establishing baseline" label rather than a suppressed or falsely-confident finding | MUST-HAVE |

**ENG-3g — Root-Cause Attribution / Explainability (SHAP)**

| ID | Subtask | Owner | Est. | Depends On | Deliverable / DoD | Priority |
|---|---|---|---|---|---|---|
| ENG-3g-1 | Implement SHAP computation against ML Ensemble feature inputs | ML Eng | 1.5 wks | ENG-3d-4 | `top_features` generated with plain-language descriptions per finding | MUST-HAVE |
| ENG-3g-2 | Build the Explainability Bundle assembler (SHAP + rule citations + STL threshold + confidence band + evidence window) | Backend Eng | 1 wk | ENG-3g-1, ENG-3f-1, ENG-3b-3 | Bundle matches the TRD v2.0 §3.7 JSON contract; persisted to `findings.explainability_bundle` | MUST-HAVE |

**ENG-3h — Feedback Loop**

| ID | Subtask | Owner | Est. | Depends On | Deliverable / DoD | Priority |
|---|---|---|---|---|---|---|
| ENG-3h-1 | Build confirm/dismiss hook in the primary review workflow + Feedback API → `feedback_labels` writes | Backend Eng + Frontend Eng | 1.5 wks | ENG-1a, ENG-5b | Confirm/dismiss happens in the workflow users already use, not a separate form | MUST-HAVE |
| ENG-3h-2 | Implement per-building retraining-eligibility counter + threshold-crossing event | Backend Eng | 1 wk | ENG-3h-1, ENG-2b | Crossing the threshold publishes a `tenant_id`-parameterized retraining-eligible event | MUST-HAVE |
| ENG-3h-3 | Implement consented cross-tenant aggregate-prior pipeline (opt-in flag, de-identified aggregate stats only) | Backend Eng | 1.5 wks | ENG-3h-1, ENG-1b | Aggregation job checks the tenant's audited opt-in flag and logs the check to `audit_log` before including that tenant's data | MUST-HAVE |

### Epic ENG-4 — Optimization Engine Productionization

Generalizes v1's OptimizerAgent logic into a standalone, evidence-grounded service (TRD v2.0 §4).

| ID | Subtask | Owner | Est. | Depends On | Deliverable / DoD | Priority |
|---|---|---|---|---|---|---|
| ENG-4a | Generalize v1's `scipy.optimize` scenario logic into a standalone service, callable synchronously (API) and as a Temporal workflow step | Backend Eng | 1.5 wks | ENG-2c | *Hackathon Origin: optimization math reused as-is*; service is callable both ways | MUST-HAVE |
| ENG-4b | Implement versioned, extensible scenario catalog (`load_shift_v1`, `setpoint_adjustment_v1`, `solar_offset_v1`) | Backend Eng | 2 wks | ENG-4a | Each scenario model is independently versioned and swappable | MUST-HAVE |
| ENG-4c | Wire scenario justification to the Explainability Bundle (`justifying_finding_ids`) | Backend Eng | 1 wk | ENG-4b, ENG-3g-2 | Every generated scenario cites ≥1 specific `finding_id` — never a generic template | MUST-HAVE |
| ENG-4d | Implement bounds-check service-level invariant (reject + log out-of-bounds results as a model-quality incident) | Backend Eng | 1 wk | ENG-4b | An implausible scenario is rejected at the service layer, never silently clipped and returned | MUST-HAVE |
| ENG-4e | Add portfolio-level call signature (multi-building rollup) | Backend Eng | 1 wk | ENG-4b | An enterprise portfolio query returns an aggregated scenario across multiple buildings | SHOULD-HAVE |

### Epic ENG-5 — API & Integrator Platform

Replaces v1's synchronous FastAPI↔Streamlit calls with a versioned, integrator-facing public API (TRD v2.0 §7).

| ID | Subtask | Owner | Est. | Depends On | Deliverable / DoD | Priority |
|---|---|---|---|---|---|---|
| ENG-5a | Stand up API Gateway (TLS termination, auth, tenant-scoped rate limiting, routing) | Platform Eng | 1.5 wks | ENG-1b | Requests are scoped to the validated token's tenant claim; a spoofed `X-Tenant-ID` header is rejected on mismatch | MUST-HAVE |
| ENG-5b | Implement core endpoint groups (Ingestion, Findings, Scenario, Reporting, Feedback, Tenant/Admin) | Backend Eng | 3 wks | ENG-5a, ENG-1a | All six endpoint groups pass contract tests | MUST-HAVE |
| ENG-5c | Implement OAuth2 client-credentials + JWT auth, path versioning, and a published deprecation policy | Backend Eng | 1 wk | ENG-5a | Deprecation policy is documented in the public API reference, not only internally | MUST-HAVE |
| ENG-5d | Implement async result delivery (202 + `poll_url` + HMAC-signed webhook) + `Idempotency-Key` support | Backend Eng | 1.5 wks | ENG-5b, ENG-2c | A retried ingestion or analysis-trigger request does not double-trigger a pipeline run | MUST-HAVE |
| ENG-5e | Build partner sandbox (dedicated isolated tenant, synthetic/anonymized data only, identical API surface) | Platform Eng | 1.5 wks | ENG-1c, ENG-5b | An integrator can develop and test against the sandbox before production access is granted | SHOULD-HAVE |

### Epic ENG-6 — MLOps Pipeline

Did not exist in v1; now load-bearing platform infrastructure (TRD v2.0 §6).

| ID | Subtask | Owner | Est. | Depends On | Deliverable / DoD | Priority |
|---|---|---|---|---|---|---|
| ENG-6a | Stand up MLflow model registry with the `{tenant_id}/{building_id}/{layer}/{version}` URI convention | Platform Eng | 1 wk | ENG-1a | ML Ensemble artifacts log correctly, including training window, trigger, and promoting actor | MUST-HAVE |
| ENG-6b | Implement training pipeline with three retraining triggers (calendar cadence, drift, feedback-volume) | ML Eng | 2 wks | ENG-3e-2, ENG-3h-2, ENG-2d | Each trigger independently schedules a retrain correctly in staging | MUST-HAVE |
| ENG-6c | Implement shadow-mode evaluation gate (false-positive-rate regression check + tiered human-review gate) | ML Eng | 1.5 wks | ENG-6b | A regressing candidate is blocked from promotion and logged with its rejection reason | MUST-HAVE |
| ENG-6d | Implement automatic rollback (post-promotion FP-rate monitor + revert to prior version) | Backend Eng | 1 wk | ENG-6c | Rollback fires without human intervention; event logged to `audit_log`; on-call alert fires | MUST-HAVE |
| ENG-6e | Implement output-distribution drift monitoring (aggregate score-distribution tracking across the tenant base) | ML Eng | 1 wk | ENG-6a | Alerting thresholds defined jointly with Data Science; silent-degradation failure mode is caught | SHOULD-HAVE |

### Epic ENG-7 — Observability & Security

Promoted from non-existent in v1 to primary infrastructure (TRD v2.0 §9.4, §9.5).

| ID | Subtask | Owner | Est. | Depends On | Deliverable / DoD | Priority |
|---|---|---|---|---|---|---|
| ENG-7a | Instrument OpenTelemetry tracing across services and across Temporal workflow executions | Platform Eng | 1.5 wks | ENG-2c, ENG-5b | A single analysis run is reconstructable end-to-end in the trace view | MUST-HAVE |
| ENG-7b | Stand up metrics/tracing backend (Prometheus/Grafana or managed equivalent) + alerting rules | Platform Eng | 1 wk | ENG-7a | Alerts fire on drift rate, FP-rate approaching ceiling, latency SLO breach, and webhook delivery failure | MUST-HAVE |
| ENG-7c | Implement secrets management (API keys, OAuth client secrets, webhook HMAC keys) | Security Eng | 1 wk | ENG-5c | Zero secrets present in application config or logs, verified by audit | MUST-HAVE |
| ENG-7d | Run SOC 2 / ISO 27001-readiness gap assessment | Security Eng + Product | 1.5 wks | ENG-1b, ENG-1e, ENG-7c | Gap list delivered to Legal/Compliance, informing PRD v2.0 OQ-2 | SHOULD-HAVE |

---

## 3. Track 2 — Research & Publication

Track 2 targets a peer-reviewable contribution in graph-aware fault localization (PRD v2.0 §7, TRD v2.0 §8), run in parallel with Track 1, not after it. **Track 1's Rule Engine (ENG-3b) and STL Residual Detection (ENG-3c) layers — and the ML Ensemble (ENG-3d) — become the topology-agnostic baseline implementations consumed directly by RES-2 below. They are not reimplemented inside the research track.** The Synthetic Fault Injection Methodology (RES-1) is the load-bearing prerequisite for everything else in this track and is sequenced first.

### Epic RES-1 — Synthetic Fault Injection Methodology

| ID | Subtask | Owner | Est. | Depends On | Deliverable / DoD | Priority |
|---|---|---|---|---|---|---|
| RES-1a | Build the fault-taxonomy injector (stuck-at-value, dropout, gradual degradation, step-change overconsumption, intermittent flicker) | Research Eng | 2 wks | ENG-1a, ENG-3a-1 | Each fault type is injectable parametrically onto a real COMBED circuit's series, preserving underlying seasonality/baseline | MUST-HAVE |
| RES-1b | Implement propagation modeling (attenuated fault signature to electrically related child circuits via `parent_circuit_id`/`panel_id`) | Research Eng | 1.5 wks | RES-1a, ENG-1a (topology fields) | Propagated signal is verified against the parent/child/panel graph structure; this is the step that makes localization the genuinely hard, topology-dependent problem | MUST-HAVE |
| RES-1c | Calibrate injection density and severity distribution per building-month | Research Eng | 1 wk | RES-1a | Density avoids both fault-saturation and too-few-instances-to-evaluate; severity spans mild/moderate/severe | MUST-HAVE |
| RES-1d | Implement k-fold split over **injection instances** (not circuits, not time windows alone) | Research Eng | 1 wk | RES-1a | Split strategy documented; no same-instance leakage across folds; the shared-topology caveat is stated explicitly | MUST-HAVE |
| RES-1e | Version and prepare the injection code + generated dataset for public release alongside any publication | Research Eng | 0.5 wk | RES-1a, RES-1b, RES-1c, RES-1d | Injection code and dataset are tagged, versioned, reproducible artifacts | SHOULD-HAVE |

### Epic RES-2 — Baseline Model Implementation

| ID | Subtask | Owner | Est. | Depends On | Deliverable / DoD | Priority |
|---|---|---|---|---|---|---|
| RES-2a | Benchmark Isolation Forest baseline, consuming Track 1's production implementation | Research Eng | 0.5 wk | ENG-3d-2, RES-1d | Baseline scored on injection-instance test folds — not reimplemented | MUST-HAVE |
| RES-2b | Benchmark Autoencoder baseline, consuming Track 1's production implementation | Research Eng | 0.5 wk | ENG-3d-3, RES-1d | Baseline scored on injection-instance test folds — not reimplemented | MUST-HAVE |
| RES-2c | Benchmark STL-residual baseline, consuming Track 1's production implementation | Research Eng | 0.5 wk | ENG-3c-1, RES-1d | Baseline scored on injection-instance test folds — not reimplemented | MUST-HAVE |
| RES-2d | Implement the scoring harness (Precision, Recall, F1, Top-1/Top-3 Localization Accuracy, AUROC) | Research Eng | 1 wk | RES-2a, RES-2b, RES-2c | Harness produces the TRD v2.0 §8.5 comparison-table format for every method | MUST-HAVE |

### Epic RES-3 — GNN Model Development

| ID | Subtask | Owner | Est. | Depends On | Deliverable / DoD | Priority |
|---|---|---|---|---|---|---|
| RES-3a | Build heterogeneous multi-relational graph construction (`electrical_parent`, `same_panel`, `same_floor` edges) | Research Eng | 1.5 wks | ENG-1a (topology schema), RES-1b | Graph object built per building directly from the canonical schema | MUST-HAVE |
| RES-3b | Implement GCN (relation-naive graph baseline) | Research Eng | 1 wk | RES-3a | GCN trains and scores on a held-out fold | SHOULD-HAVE |
| RES-3c | Implement GAT (primary candidate; attention weights as an interpretability signal) | Research Eng | 2 wks | RES-3a | GAT trains and scores; attention weights are extractable per prediction | MUST-HAVE |
| RES-3d | NILM transfer-learning pretraining (REDD / UK-DALE / Dataport) before COMBED fine-tuning | Research Eng | 2.5 wks | RES-3c | Pretrained encoder is fine-tuned on COMBED's topology; addresses PRD v2.0 §7.4's generalization-risk mitigation | SHOULD-HAVE |
| RES-3e | Wire the per-node binary fault-source classification task + training loop on synthetic injection labels | Research Eng | 1 wk | RES-3c, RES-1d | Task trains correctly on RES-1's injection-instance labels | MUST-HAVE |

### Epic RES-4 — Comparative Evaluation Study

| ID | Subtask | Owner | Est. | Depends On | Deliverable / DoD | Priority |
|---|---|---|---|---|---|---|
| RES-4a | Run the full baseline-vs-GNN comparison across all k-folds | Research Eng | 1.5 wks | RES-2d, RES-3e | The TRD v2.0 §8.5 table is populated with real, non-placeholder numbers for every method | MUST-HAVE |
| RES-4b | Statistical significance testing (Wilcoxon signed-rank test or bootstrap CIs, pre-registered threshold + effect size) | Research Eng | 1 wk | RES-4a | Paired significance results are reported alongside point estimates, not a bare comparison | MUST-HAVE |
| RES-4c | Honest-reporting pass — document every case where the GNN does *not* outperform a baseline | Research Eng | 0.5 wk | RES-4b | Write-up explicitly enumerates non-wins, per PRD v2.0 §7.3's acceptance criterion | MUST-HAVE |
| RES-4d | Internal methodology review (leakage across folds, overfitting to the single building, statistical validity) | Senior ML/Research Reviewer | 1 wk | RES-4b | Signed-off review memo exists before any external submission is committed to | MUST-HAVE |

### Epic RES-5 — Paper Writing & Submission

| ID | Subtask | Owner | Est. | Depends On | Deliverable / DoD | Priority |
|---|---|---|---|---|---|---|
| RES-5a | Literature review + novelty-delta positioning against existing FDD literature | Research Eng | 2 wks | — *(can start in parallel, early)* | Positioning memo names the specific delta (heterogeneous edges + propagation-aware injection), addressing the IEEE-novelty risk | MUST-HAVE |
| RES-5b | Target venue identification (*placeholder: IEEE smart-buildings/FDD conference or workshop*) + submission-window lock (*placeholder deadline*) | Research Lead + Product | 0.5 wk | RES-5a, RES-4a (preliminary results) | Venue and deadline locked jointly per PRD v2.0 §8.5 | MUST-HAVE |
| RES-5c | Draft manuscript — methodology, results, honest dataset-limitation discussion (PRD v2.0 §7.4) | Research Eng | 3 wks | RES-4c, RES-4d | Full draft ready for internal review | MUST-HAVE |
| RES-5d | Internal review and revision pass | Research Lead | 1 wk | RES-5c | Draft incorporates reviewer feedback | MUST-HAVE |
| RES-5e | Submit manuscript + reproducibility artifacts | Research Lead | 0.5 wk | RES-5d, RES-5b | Manuscript and the versioned injection dataset/code (RES-1e) are submitted together | MUST-HAVE |

---

## 4. Track 3 — Pilot & Go-to-Market Validation

Track 3 validates the production platform and the business model against real buildings and real customers — not the COMBED fixture, and not a hackathon judge.

### Epic GTM-1 — Pilot Customer Onboarding

| ID | Subtask | Owner | Est. | Depends On | Deliverable / DoD | Priority |
|---|---|---|---|---|---|---|
| GTM-1a | Define pilot cohort (2–3 SME single-building pilots + ≥1 enterprise multi-building portfolio pilot) | Product | 1 wk | — | Pilot cohort list approved, spanning both buyer segments per PRD v2.0 §8.3 | MUST-HAVE |
| GTM-1b | Onboard pilot buildings via real ingestion paths (CSV and/or smart-meter API) | Backend Eng + Product | 2 wks | ENG-5b, ENG-3a-1 | Each pilot building clears onboarding validation and produces a data-quality status | MUST-HAVE |
| GTM-1c | Validate cold-start mode against real pilot data | ML Eng | 1 wk | GTM-1b, ENG-3f-2 | Cold-start pilot buildings surface honestly-labeled low-confidence findings, not falsely-confident ones | MUST-HAVE |

### Epic GTM-2 — Real-World Validation

| ID | Subtask | Owner | Est. | Depends On | Deliverable / DoD | Priority |
|---|---|---|---|---|---|---|
| GTM-2a | Compare production findings against pilot facility managers' ground-truth knowledge (real data, not just COMBED) | Product + ML Eng | 2 wks | GTM-1b | Precision/recall on real-world confirmed/dismissed findings tracked per pilot building | MUST-HAVE |
| GTM-2b | Validate Optimization Engine scenario outputs against pilot buildings' actual utility bills | Product | 1.5 wks | GTM-1b, ENG-4d | Scenario estimates fall within the bounds-checked plausible range against real billing data | MUST-HAVE |

### Epic GTM-3 — Feedback Loop Effectiveness Measurement

| ID | Subtask | Owner | Est. | Depends On | Deliverable / DoD | Priority |
|---|---|---|---|---|---|---|
| GTM-3a | Instrument false-positive-rate-over-time tracking per pilot building — the metric that actually validates Layer 8's design | ML Eng | 1 wk | ENG-3h-2, GTM-1b | A measurable FP-rate trend exists per pilot building | MUST-HAVE |
| GTM-3b | Surface the feedback loop's value visibly to pilot users (a trend view, per PRD v2.0 §5.5) | Frontend Eng | 1 wk | GTM-3a | A facility manager can see their own FP-rate improving over time | SHOULD-HAVE |

### Epic GTM-4 — Pricing & Packaging Validation

| ID | Subtask | Owner | Est. | Depends On | Deliverable / DoD | Priority |
|---|---|---|---|---|---|---|
| GTM-4a | Validate the freemium-to-paid conversion hypothesis with SME pilots | Product | 2 wks | GTM-1b | Conversion data informs PRD v2.0 OQ-1's pricing-tier decision | MUST-HAVE |
| GTM-4b | Validate enterprise contract structure and API/platform-tier pricing with the integrator pilot | Product | 2 wks | GTM-1b, ENG-5e | Pricing hypothesis validated or revised with real partner input | SHOULD-HAVE |

---

## 5. Cross-Track Dependencies

This graph replaces v1's single linear Phase 0→5 chain. It is not exhaustive of every within-track dependency already shown in Sections 2–4 — only the dependencies that **cross** a track boundary.

| Upstream | Downstream | Nature of dependency |
|---|---|---|
| ENG-1a (canonical schema, topology fields) | RES-1b, RES-3a | The injection-propagation model and the GNN's graph construction both read `parent_circuit_id`/`panel_id`/`floor` directly from the production schema — no separate research data model. |
| ENG-3a-1 (Data Quality Gate) | RES-1a | Synthetic fault injection perturbs real `normalized_readings`, not raw uncleaned data. |
| ENG-3c-1 (STL Residual) | RES-2c | Baseline Model Implementation consumes the production STL implementation directly — do not reimplement. |
| ENG-3d-2, ENG-3d-3 (ML Ensemble) | RES-2a, RES-2b | Baseline Model Implementation consumes the production Isolation Forest and Autoencoder directly — do not reimplement. |
| RES-1 (Synthetic Fault Injection Methodology) | RES-3 (GNN Model Development) | **Blocks.** No labeled localization signal exists for GNN training/evaluation until the injection methodology (with propagation modeling) is complete. |
| RES-4 (Comparative Evaluation Study) | ENG-3g (Root-Cause Attribution) | **Feeds, future-scoped.** A validated GNN result becomes a *candidate addition* to Root-Cause Attribution once it clears the publishable bar (PRD v2.0 §7.5) — this is a Year 2 product/research convergence point, not an active subtask in this roadmap's milestones. |
| ENG-5b, ENG-5e (API Platform + Sandbox) | GTM-1b, GTM-4b | Pilot onboarding and the integrator pilot both require real ingestion endpoints and, for the integrator, a sandbox environment. |
| ENG-6 (MLOps gates) | GTM-1c, GTM-2a | Pilot buildings cannot be safely retrained on real feedback data until promotion gating and rollback (ENG-6c, ENG-6d) exist. |
| ENG-3h (Feedback Loop) | GTM-3 | FP-rate-over-time measurement requires the confirm/dismiss infrastructure and retraining-eligibility counter to already exist. |
| ENG-7d (SOC 2/ISO 27001 readiness) | GTM-1a (enterprise pilot candidate selection) | Compliance-sensitive enterprise pilot prospects (PRD v2.0 §4.2, §4.4) are qualified in part against the platform's compliance posture. |

---

## 6. Milestones & Sequencing

v1's single 🔴 Critical Path protected one live demo. v2 has two named milestones, each scoped to its own track, replacing the demo-centric framing entirely.

### 🔵 Minimum Viable Production Platform

The smallest set of Track 1 epics required before a real pilot customer can be onboarded (i.e., the prerequisite for Track 3 to begin in earnest).

**Gating subtasks (all MUST-HAVE):** `ENG-1a, ENG-1b, ENG-1c, ENG-1e, ENG-1f` · `ENG-2a, ENG-2b, ENG-2c, ENG-2d` · `ENG-3a-1, ENG-3a-2, ENG-3a-4` · `ENG-3b-1, ENG-3b-2, ENG-3b-3` · `ENG-3c-1, ENG-3c-2` · `ENG-3d-1, ENG-3d-2, ENG-3d-3, ENG-3d-4` · `ENG-3e-1, ENG-3e-2` · `ENG-3f-1, ENG-3f-2` · `ENG-3g-1, ENG-3g-2` · `ENG-3h-1, ENG-3h-2, ENG-3h-3` · `ENG-4a, ENG-4b, ENG-4c, ENG-4d` · `ENG-5a, ENG-5b, ENG-5c, ENG-5d` · `ENG-6a, ENG-6b, ENG-6c, ENG-6d` · `ENG-7a, ENG-7b, ENG-7c`

A pilot building cannot be onboarded credibly until every one of these clears: a tenant whose data isn't isolated, whose pipeline can't recover from a transient failure, or whose model can be promoted without a regression gate is not a pilot-ready platform regardless of how many epics are "mostly done."

### 🟢 Minimum Submittable Research Result

The smallest set of Track 2 epics required to have a submittable paper draft.

**Gating subtasks (all MUST-HAVE):** `RES-1a, RES-1b, RES-1c, RES-1d` · `RES-2a, RES-2b, RES-2c, RES-2d` · `RES-3a, RES-3c, RES-3e` · `RES-4a, RES-4b, RES-4c, RES-4d` · `RES-5a, RES-5b, RES-5c, RES-5d, RES-5e`

`RES-1e` (public dataset release), `RES-3b` (GCN ablation), and `RES-3d` (NILM transfer learning) are SHOULD-HAVE strengthening work — valuable to the paper's robustness and worth completing if the timeline allows, but their absence does not block a submittable draft, since the core GAT-vs-baselines comparison (RES-2 + RES-3c/3e + RES-4) stands on its own.

---

## 7. Risk Register

Cross-referenced against PRD v2.0 §10 and TRD v2.0 §12. Every risk named in either document is mapped to the track/epic that owns mitigating it; no risk is duplicated as a separate Track 3 item where a Track 1 or Track 2 epic already owns the mitigation.

| Risk (PRD §10 / TRD §12) | Owning Track/Epic | Mitigation mechanism |
|---|---|---|
| Data privacy / multi-tenancy breach | ENG-1 (RLS, isolation tiers), ENG-7 (security, secrets mgmt) | Isolation enforced at the database layer (ENG-1b), tenant-isolation fuzzer in CI (ENG-1f), incident-response readiness (ENG-7d) |
| Model drift across heterogeneous building types | ENG-3e (Drift Detection), ENG-6 (MLOps retraining triggers) | Per-`(building_type, climate_zone)`-conditioned drift sensitivity, not a single global threshold; new building types validated as onboarded |
| Cold-start for new buildings with no history | ENG-1a (`cold_start` flag), ENG-3f-2 (calibration default), GTM-1c (real-pilot validation) | Domain Rule Engine as primary high-confidence source during cold-start; wide confidence bands enforced architecturally, not left to a downstream consumer |
| Customer trust failure if explainability is weak | ENG-3g (Explainability Bundle), ENG-5 (LLM system-prompt hard rules per TRD v2.0 §5.2) | Low-confidence findings surfaced honestly, never upgraded into confident-sounding prose; confidence_band is a required field |
| IEEE reviewer novelty risk | RES-5a (literature review + delta positioning) | Thorough literature review precedes any submission-timeline commitment; explicit willingness to sharpen the claimed delta if narrower than hoped |
| Dataset limitation undermining research credibility | RES-1 (propagation-aware injection), RES-3d (NILM transfer learning) | Both are named, real methodological mitigations, not a hand-wave; the limitation is stated plainly in the write-up (RES-5c), not minimized |
| Temporal operational complexity exceeds team's ops maturity *(TRD §12 only)* | ENG-2 (Orchestration), specifically ENG-2e | Start with Temporal Cloud (managed); documented, reversible fallback to Celery+Redis if needed pre-PMF |
| TimescaleDB write-throughput bottleneck at scale *(TRD §12 only)* | ENG-1 (Data Architecture), ENG-2b (event backbone decoupling) | Event-backbone decoupling means an analysis-side bottleneck doesn't block ingestion acknowledgment; documented partial-migration escalation path if the write path itself bottlenecks |
| GNN training/evaluation compute or engineering time competes with the production roadmap's capacity *(TRD §12 only)* | RES-3 (feature reuse from ENG-3) | Research node features are reused directly from the production feature pipeline (RES-3a depends on ENG-1a, not a parallel feature-computation path) — the marginal cost is graph-construction and training only |

---

## Appendix: Migration Map

**A note on scope before this table:** the materials provided for this rewrite were PRD v2.0 and TRD v2.0. The original **ROADMAP.md v1** file itself was not included in the upload this roadmap was built from — only its structure and contents as *described in the rewrite instructions*, and as independently cross-referenced inside PRD v2.0's own Appendix: Migration Map and TRD v2.0's own Appendix A, were available. The table below is built from those two sources and is accurate at the **phase/component level** (which v1 phases, agents, and hackathon-specific artifacts existed, and where their functionality or their "complete" status lands in v2). It does **not** claim to reproduce v1's literal hour-by-hour subtask IDs, since those were not in the source material reviewed. If the actual ROADMAP.md v1 file is provided, this appendix should be re-verified against it line-by-line.

| v1 Roadmap Item | Status | v2.0 Destination |
|---|---|---|
| 4-day, hour-by-hour build window; Day 1–3 hard cutoffs; Day 4 polish-only | Removed entirely | No equivalent — production roadmap timing is strategic (Sections 6–7), not build-day cutoffs |
| Named individual owners (Member 1, 2, 3, 4) | Removed entirely | Replaced by role-based ownership throughout Sections 2–4 (Backend Eng, ML Eng, Research Eng, Product, etc.) |
| Single 🔴 Critical Path, framed around "the live demo breaking" | Removed entirely | Replaced by two milestones scoped per-track: 🔵 Minimum Viable Production Platform and 🟢 Minimum Submittable Research Result (Section 7) |
| "Phase 1: Data Foundation" — load 2–3 golden CSVs | Complete — hackathon MVP validated this | Superseded by Epic ENG-1 Multi-Tenant Data Architecture (proper multi-tenant onboarding; the golden-CSV fixture survives only as a test fixture, TRD v2.0 §11.1) |
| SensorAgent (ingestion, normalization, derived signals) | Complete — hackathon MVP validated the underlying logic | Logic carried forward into Epic ENG-3a Data Quality Gate (ENG-3a-1); "SensorAgent" naming dropped |
| AnomalyAgent (single Isolation Forest + rule-based detection) | Complete — hackathon MVP validated the core idea; architecture itself superseded | Fully superseded by the eight-layer Epic ENG-3 Anomaly Intelligence Platform Build-Out; Isolation Forest survives only as one member of ENG-3d, never again "the" detector |
| OptimizerAgent (load shifting, setpoint, solar scenarios via `scipy.optimize`) | Complete — hackathon MVP validated the math | Logic carried forward into Epic ENG-4 Optimization Engine Productionization (ENG-4a); "OptimizerAgent" naming dropped |
| NarratorAgent (LLM narrative + action plan generation, schema validation, retry/fallback) | Complete — hackathon MVP validated the pattern | Structural pattern (JSON-in/JSON-out, retry-then-fallback) reused unchanged inside the Explainability & Reporting Service that underlies ENG-3g/ENG-4c's consumers; system prompt itself is rewritten, not reused verbatim, per TRD v2.0 §5 |
| Dashboard (Streamlit-specific UI, "watch 4 agents light up" progress panel) | Removed as a named implementation; underlying user need superseded | Demo-credibility device removed entirely; substantive trust mechanisms (confidence calibration ENG-3f, audit logs ENG-1e, explainability ENG-3g) replace it as the actual trust-building surface |
| Report Engine (WeasyPrint PDF, fixed 4–6 page spec) | Complete — hackathon MVP validated the rendering approach | WeasyPrint retained as a rendering technology inside a standalone Reporting microservice; decoupled from the Streamlit-Cloud deployment target and the fixed page-count spec |
| Sample-building fallback (3–5 pre-loaded sample buildings) | Removed entirely | Judge-demo-specific convenience; superseded by real onboarding flows (Epic GTM-1) |
| Live agent visibility / "watching 4 agents work" | Removed entirely | Demo-credibility device; superseded by substantive trust mechanisms per PRD v2.0 §5.2/§6 (same disposition as the Dashboard row above) |
| ≤90-second end-to-end demo SLA | Removed as a headline metric | Demoted to one latency target among several, differentiated by ingestion path, in TRD v2.0 §9.1 (no single ENG epic "owns" this any longer — it's a cross-cutting NFR) |
| Zero paid dependencies / free-tier-only constraint (Streamlit Cloud, Claude API limits, no paid infra) | Removed entirely | Superseded by paid production infrastructure throughout Track 1 (PRD v2.0 §9 Infrastructure Cost Assumptions) |
| ngrok tunnel as Streamlit Cloud backup | Removed entirely | No equivalent — a managed API Gateway (ENG-5a) and real deployment infrastructure replace any tunnel-as-fallback pattern |
| CrewAI/LangGraph orchestration framework (and its version-incompatibility risk) | Removed entirely | Superseded by Temporal as the named orchestrator (Epic ENG-2); v2 does not depend on either framework |
| Rehearse pitch; record backup demo video | Removed entirely — historical, hackathon-specific | Acknowledged only in this document's Preamble as part of "what the hackathon MVP proved"; no v2 roadmap equivalent |
| Team Responsibility Matrix (4-person hackathon team roles) | Removed entirely | No equivalent — organizational/staffing structure is a leadership decision made against role-based ownership (Section 1), not a roadmap appendix |
| Hackathon technical risks: WeasyPrint-on-Streamlit-Cloud dependency; team-coordination bottleneck | Removed entirely | No v2 equivalent; see Section 7 Risk Register for the risks that do carry forward (multi-tenancy, drift, cold-start, explainability trust, IEEE novelty, dataset limitation) |

---

*CarbonSense ROADMAP v2.0 · Built from PRD v2.0 and TRD v2.0 · Last updated: June 2026*
