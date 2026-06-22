# CarbonSense — Technology Stack Lock

**Version:** 1.0
**Status:** Active — Binding for all implementation work
**Source of Truth for Decisions:** TRD v2.0 §10 (Tech Stack Table), PRD v2.0, ROADMAP v2.0
**Document Owner:** Engineering
**Last Updated:** 2026-06-21

---

## Purpose

This document is the **single source of truth** for every technology, framework,
library, version, and development standard used in CarbonSense. No implementation
prompt, PR, or epic may introduce a technology that conflicts with this document
without an explicit, reviewed amendment recorded here and in `docs/ADRs/`.

**How to read this document:**
- **LOCKED** — decided, ratified, do not deviate.
- **PREFERRED** — strong default; deviate only with an ADR justifying the exception.
- **OPEN** — not yet decided; resolve before the dependent epic begins.

---

## 1. Runtime & Language

| Item | Decision | Detail |
|---|---|---|
| Language | **LOCKED** — Python | All backend services, ML pipelines, orchestration workers, and research code. TRD v2.0 §10: "team familiarity" + async-native ecosystem. |
| Minimum Version | **LOCKED** — Python 3.11 | Set in `pyproject.toml` (`requires-python = ">=3.11"`). Required for `TaskGroup`, `ExceptionGroup`, and `tomllib` stdlib support. |
| Target Runtime | **LOCKED** — Python 3.12 | Recommended for all new environments. 3.12 provides improved error messages, `f-string` grammar relaxation, and ~5% interpreter performance improvement over 3.11. CI matrix tests against both 3.11 and 3.12. |
| Upgrade Policy | Adopt new CPython stable releases within 6 months of GA, gated on dependency compatibility. Never run a version that has reached end-of-life. |

---

## 2. Core Stack

### 2.1 Web Framework — FastAPI

| | |
|---|---|
| **Purpose** | API Gateway, service-layer HTTP endpoints, model-serving microservice |
| **Selected Version** | **LOCKED** — `fastapi >= 0.115` / `uvicorn >= 0.30` |
| **Reason for Selection** | Async-native, strong typing/validation via Pydantic, OpenAPI auto-generation, team familiarity. TRD v2.0 §10: "Reused as a component — the framework choice survives." |
| **Alternatives Considered** | **Django REST Framework** — heavier ORM coupling, synchronous by default, unnecessary given no server-rendered UI. **Litestar** — capable async alternative but smaller ecosystem and team has no prior experience. **gRPC** — considered for internal service-to-service calls; deferred as premature — REST+JSON is sufficient at current service count. |
| **Upgrade Policy** | Track FastAPI minor releases. Pin major version in `pyproject.toml`; upgrade when Pydantic or Starlette dependencies require it. |

**Pydantic** (transitive via FastAPI):
- **LOCKED** — `pydantic >= 2.7`
- All data contracts, settings models, and API request/response schemas use Pydantic v2 models exclusively. No v1-style `class Config` patterns.

### 2.2 Database — PostgreSQL + TimescaleDB

| | |
|---|---|
| **Purpose** | Tenant-isolated relational + time-series storage (tenants, buildings, circuits, normalized_readings hypertable, findings, feedback_labels, audit_log) |
| **Selected Version** | **LOCKED** — PostgreSQL 16 + TimescaleDB 2.x extension |
| **Reason for Selection** | RLS-enforced multi-tenant isolation + relational joins + time-series hypertables in one engine. One backup/restore story, one HA story, one access-control model. TRD v2.0 §2.3: "This platform's hardest non-negotiable requirement is multi-tenant isolation enforced at the storage layer, and that requirement is most naturally satisfied by Postgres RLS." |
| **Alternatives Considered** | **InfluxDB** — no first-class row-level security; relational joins are awkward; would require running two database engines (InfluxDB for time-series + Postgres for relational) doubling operational surface. **ClickHouse** — strong for analytics but weak for OLTP write patterns and RLS enforcement. **CockroachDB** — distributed SQL but adds complexity with no current scale justification. |
| **Upgrade Policy** | Track PostgreSQL major releases (annual). Upgrade within 6 months of a new stable release. TimescaleDB extension follows its own release cadence — pin to 2.x, evaluate 3.x when stable. |

**Escalation path** (TRD v2.0 §12): If real-time smart-meter API ingestion volume exceeds TimescaleDB's comfortable write-throughput range, evaluate a dedicated TSDB for the `normalized_readings` hypertable specifically (InfluxDB or TimescaleDB Hyperscale tier) while keeping relational data on standard Postgres. This is a partial migration, not a re-architecture.

### 2.3 ORM & Query Layer — SQLAlchemy

| | |
|---|---|
| **Purpose** | Database access layer, model definitions, query construction, connection pooling, RLS context management (`app.current_tenant_id` per-request) |
| **Selected Version** | **LOCKED** — `sqlalchemy >= 2.0` (2.x style only) |
| **Reason for Selection** | Industry standard Python ORM with mature async support (`asyncio` extension), first-class PostgreSQL dialect, and the `session.execute(text("SET app.current_tenant_id = :tid"))` pattern needed for RLS context injection per TRD v2.0 §2.2. |
| **Alternatives Considered** | **Raw asyncpg** — faster for pure query execution but loses ORM conveniences (migration compatibility, model-as-code, relationship loading) that are valuable given 7+ tenant-scoped tables with FK relationships. **Tortoise ORM** — async-native but smaller ecosystem and less mature migration tooling than Alembic. **SQLModel** — Pydantic+SQLAlchemy hybrid; considered but adds a coupling layer between API schemas and DB models that should remain separate in a multi-service architecture. |
| **Upgrade Policy** | Track SQLAlchemy 2.x minor releases. Use 2.x-style `select()` / `Session` patterns exclusively — no 1.x legacy `Query` API. |

**Async driver**: `asyncpg >= 0.29` as the PostgreSQL async driver underneath SQLAlchemy's async engine. Do not use `psycopg2` in async code paths.

### 2.4 Database Migrations — Alembic

| | |
|---|---|
| **Purpose** | Schema migration management — all DDL changes to the canonical schema (TRD v2.0 §2.2) |
| **Selected Version** | **LOCKED** — `alembic >= 1.13` |
| **Reason for Selection** | The standard migration tool for SQLAlchemy. Supports auto-generation from model diffs, branching migration histories, and programmatic migration execution from Temporal workflows. |
| **Alternatives Considered** | **Django migrations** — requires Django; not applicable. **Flyway** — JVM-based; wrong ecosystem. **Manual DDL scripts** — no version tracking, no rollback, no auto-generation. |
| **Upgrade Policy** | Track Alembic minor releases alongside SQLAlchemy. |

**Rules** (per REPOSITORY_STRUCTURE_TRACK1.md):
- All schema changes go through `database/migrations/`.
- Migration files are version-controlled and reviewed in PRs.
- No hand-edited DDL applied directly to production — Alembic is the single migration path.

### 2.5 Workflow Orchestration — Temporal

| | |
|---|---|
| **Purpose** | Durable, resumable execution of the multi-layer analysis pipeline, scheduled batch jobs (drift detection, retraining), human-in-the-loop feedback waits |
| **Selected Version** | **LOCKED** — `temporalio >= 1.7` (Python SDK) / Temporal Cloud (managed control plane) |
| **Reason for Selection** | TRD v2.0 §1.2 provides the full justification: (1) the pipeline is a long-running, multi-step, partially-failable saga, not a fire-and-forget task; (2) human-in-the-loop steps (feedback confirm/dismiss) are first-class via signal/query primitives; (3) scheduled cron workflows and the same dashboard/replay tooling cover both real-time and batch paths. |
| **Alternatives Considered** | **Celery + Redis** — gives a task queue, not a resumable state machine; would require hand-building Temporal's core value proposition (durable execution, signals, queries). Documented as a deliberate, reversible fallback (TRD v2.0 §12) if Temporal Cloud's operational overhead proves too heavy pre-PMF. **Apache Airflow** — DAG-based batch scheduler, not designed for request-path latency-sensitive workflows or human-in-the-loop waits. **Prefect** — viable but less mature durable-execution semantics and smaller enterprise adoption. |
| **Upgrade Policy** | Track Temporal Python SDK minor releases. Temporal Cloud manages server-side upgrades. |

**Deployment**: Start with **Temporal Cloud** (managed), not self-hosted Temporal Server. Revisit self-hosting only if cost or data-residency requirements demand it.

**Fallback path** (TRD v2.0 §1.2, ROADMAP ENG-2e): If Temporal Cloud proves too heavy pre-PMF, fall back to `celery >= 5.4` + `redis >= 5.0`. This is a deliberate, reversible downgrade with known costs (hand-built resumability and human-in-loop waits).

### 2.6 Event Backbone — Kafka

| | |
|---|---|
| **Purpose** | Durable event stream decoupling ingestion from analysis pipeline triggering. Core events: `building.data.arrived`, `finding.confirmed`, `model.promoted`, `model.drift.detected` |
| **Selected Version** | **LOCKED** — Apache Kafka 3.x (via managed service) / `confluent-kafka >= 2.5` (Python client) |
| **Reason for Selection** | TRD v2.0 §1.2: "The event backbone sits upstream of Temporal: ingestion services publish events; a lightweight event consumer starts the corresponding Temporal workflow execution. This keeps ingestion decoupled from analysis." |
| **Alternatives Considered** | **Redis Streams** — lighter operationally but lacks Kafka's durability guarantees, partitioned consumer groups, and schema-registry ecosystem needed for a multi-service event backbone. **RabbitMQ** — message broker, not a durable log; doesn't support replay or consumer-group semantics as naturally. **Amazon SQS/SNS** — viable managed alternative but vendor-locked; Kafka's managed equivalents (MSK, Confluent Cloud) are preferred for portability. |
| **Upgrade Policy** | Managed service handles broker upgrades. Track `confluent-kafka` Python client minor releases. |

**Managed service options** (TRD v2.0 §10): Amazon MSK or Confluent Cloud. Choose based on existing cloud provider relationship. Do not self-host Kafka pre-PMF.

**Alternative Python client**: `aiokafka >= 0.10` if async-native integration with FastAPI's event loop is required for the ingestion consumer. Evaluate during ENG-2b; default to `confluent-kafka` for its maturity and librdkafka performance.

### 2.7 Model Registry — MLflow

| | |
|---|---|
| **Purpose** | Per-tenant/per-building versioned model tracking, promotion/rollback metadata, training experiment logging |
| **Selected Version** | **LOCKED** — `mlflow >= 2.15` |
| **Reason for Selection** | TRD v2.0 §6.1: "MLflow serves as the model registry. URI convention: `models:/{tenant_id}/{building_id}/{layer}/{version}`." Open-source, framework-agnostic, supports the promotion/staging/production lifecycle and artifact storage. |
| **Alternatives Considered** | **Weights & Biases** — stronger experiment tracking UI but SaaS-only for the registry; adds a vendor dependency and per-seat cost for a capability MLflow provides adequately. **DVC** — git-based versioning; good for dataset versioning but not designed for the multi-tenant model lifecycle (promotion gates, rollback) that ENG-6 requires. **Custom registry** — unnecessary build when MLflow covers the requirements. |
| **Upgrade Policy** | Track MLflow minor releases quarterly. Pin major version. |

**URI convention** (binding): `models:/{tenant_id}/{building_id}/{layer}/{version}` — all downstream services key off this literal pattern.

### 2.8 ML & Scientific Computing

#### 2.8.1 PyTorch

| | |
|---|---|
| **Purpose** | Windowed Autoencoder (ENG-3d), GNN research models — GCN and GAT (RES-3b, RES-3c) |
| **Selected Version** | **LOCKED** — `torch >= 2.3` |
| **Reason for Selection** | TRD v2.0 §10 lists "Keras or PyTorch" for the Autoencoder and PyTorch Geometric for the GNN stack. Locking to PyTorch unifies the deep learning runtime across production (Autoencoder) and research (GNN), avoiding a Keras/TF + PyTorch split that doubles dependency weight and debugging surface. |
| **Alternatives Considered** | **TensorFlow/Keras** — viable for the Autoencoder alone, but the GNN research track requires PyTorch Geometric (no equivalent TF library at maturity parity), so running both frameworks doubles dependencies for no gain. **JAX** — strong for research but weaker serving ecosystem and team familiarity. |
| **Upgrade Policy** | Track PyTorch minor releases. Pin to CUDA version compatible with deployment infrastructure. |

#### 2.8.2 PyTorch Geometric

| | |
|---|---|
| **Purpose** | GNN research — GCN/GAT implementations, heterogeneous graph support (RES-3) |
| **Selected Version** | **LOCKED** — `torch-geometric >= 2.5` |
| **Reason for Selection** | TRD v2.0 §10: "Standard library for GCN/GAT implementations and heterogeneous-graph support." |
| **Alternatives Considered** | **DGL (Deep Graph Library)** — comparable capability but PyG has stronger heterogeneous-graph-specific APIs (`HeteroData`, `HeteroConv`) matching the multi-relational edge structure in TRD §8.2. |
| **Upgrade Policy** | Track alongside PyTorch version compatibility. Research-only until GNN clears the production go/no-go bar (PRD §7.5). |

#### 2.8.3 scikit-learn

| | |
|---|---|
| **Purpose** | Isolation Forest (ENG-3d), general ML utilities |
| **Selected Version** | **LOCKED** — `scikit-learn >= 1.5` |
| **Reason for Selection** | TRD v2.0 §10: Isolation Forest reused from v1 hackathon. Mature, well-validated, minimal dependency footprint. |
| **Upgrade Policy** | Track minor releases. |

#### 2.8.4 statsmodels

| | |
|---|---|
| **Purpose** | STL seasonal-trend decomposition (ENG-3c) |
| **Selected Version** | **LOCKED** — `statsmodels >= 0.14` |
| **Reason for Selection** | TRD v2.0 §10: "Standard, well-validated implementation" of `statsmodels.tsa.seasonal.STL`. Reused from v1. |
| **Upgrade Policy** | Track minor releases. |

#### 2.8.5 SciPy

| | |
|---|---|
| **Purpose** | Optimization Engine linear programming — `scipy.optimize` for load-shifting, setpoint adjustment, solar offset scenarios (ENG-4) |
| **Selected Version** | **LOCKED** — `scipy >= 1.13` |
| **Reason for Selection** | TRD v2.0 §4 / ROADMAP ENG-4a: "v1's `scipy.optimize` scenario logic... reused as-is." |
| **Upgrade Policy** | Track minor releases. |

#### 2.8.6 SHAP

| | |
|---|---|
| **Purpose** | Root-Cause Attribution — model-agnostic feature attribution for the ML Ensemble's predictions (ENG-3g) |
| **Selected Version** | **LOCKED** — `shap >= 0.45` |
| **Reason for Selection** | TRD v2.0 §3.7 / §10: "Standard, model-agnostic explainability over the ML Ensemble's feature inputs." SHAP values decompose each finding into the specific engineered features that drove it, producing the `top_features` field in the Explainability Bundle. |
| **Alternatives Considered** | **LIME** — instance-level but less theoretically grounded attribution; no unified feature-importance guarantees. **Captum** — PyTorch-specific; doesn't cover the scikit-learn Isolation Forest. **Custom permutation importance** — ad hoc, not standardized, harder to validate. |
| **Upgrade Policy** | Track minor releases. |

#### 2.8.7 Conformal Prediction

| | |
|---|---|
| **Purpose** | Confidence Calibration layer — statistically grounded uncertainty bounds per finding (ENG-3f) |
| **Selected Version** | **PREFERRED** — `mapie >= 0.9` |
| **Reason for Selection** | TRD v2.0 §10: "Conformal prediction (e.g., MAPIE or a custom implementation)." MAPIE provides a ready-made conformal wrapper compatible with scikit-learn estimators. |
| **Alternatives Considered** | **Custom implementation** — viable if MAPIE's API doesn't fit the rolling per-building calibration set pattern (ENG-3f-2). Decision: start with MAPIE; if the per-building rolling-calibration-set requirement forces custom code, implement it in `services/calibration/` and document the decision in an ADR. |
| **Upgrade Policy** | Track minor releases. |

#### 2.8.8 Drift Detection

| | |
|---|---|
| **Purpose** | Mann-Kendall trend test on rolling efficiency ratio (ENG-3e) |
| **Selected Version** | **PREFERRED** — `pymannkendall >= 1.4` |
| **Reason for Selection** | TRD v2.0 §10: "Mann-Kendall trend test (`pymannkendall` or equivalent)." Standard nonparametric trend test. |
| **Upgrade Policy** | Stable library; minimal release cadence. |

### 2.9 LLM Integration — Claude API

| | |
|---|---|
| **Purpose** | Reporting Service — structured JSON-in/JSON-out narrative generation for Carbon Action Plans (TRD v2.0 §5) |
| **Selected Version** | **LOCKED** — `anthropic >= 0.39` (Anthropic Python SDK) |
| **Reason for Selection** | TRD v2.0 §10: "Claude API — Retained: structured JSON-in/JSON-out, schema validation, retry-then-fallback pattern — proven sound in v1." |
| **Model Selection** | Use the latest Claude Sonnet model for cost-efficient structured output. Evaluate Claude Opus for complex multi-finding reports if narrative quality requires it. Model ID is a runtime config value (`ANTHROPIC_MODEL` in `.env`), not hardcoded. |
| **Upgrade Policy** | Track Anthropic SDK releases. Model upgrades are runtime configuration changes, not code changes. |

### 2.10 Report Rendering — WeasyPrint

| | |
|---|---|
| **Purpose** | PDF report generation from HTML/CSS templates (TRD v2.0 §5.4) |
| **Selected Version** | **LOCKED** — `weasyprint >= 62` |
| **Reason for Selection** | TRD v2.0 §10: "Retained as a rendering technology; now runs inside its own Reporting microservice on standard container infrastructure, not coupled to a Streamlit-Cloud deployment target." |
| **Alternatives Considered** | **Puppeteer/Playwright** — headless browser rendering; heavier container footprint for equivalent output quality. **ReportLab** — programmatic PDF; more code for layout-intensive reports vs. HTML/CSS templating. **LaTeX** — overkill; facility managers don't need typeset documents. |
| **Upgrade Policy** | Track minor releases. |

---

## 3. Infrastructure & DevOps

### 3.1 Infrastructure as Code — Terraform

| | |
|---|---|
| **Purpose** | Reproducible provisioning of all cloud infrastructure — hybrid isolation model (shared-RLS + dedicated-schema/DB per tenant), TimescaleDB, Kafka, S3, Temporal Cloud namespace, monitoring stack |
| **Selected Version** | **LOCKED** — Terraform >= 1.8 (OpenTofu >= 1.7 accepted as compatible alternative) |
| **Reason for Selection** | TRD v2.0 §10: "Reproducible provisioning of the hybrid isolation model's per-tenant schema/database resources." REPOSITORY_STRUCTURE_TRACK1.md Rule 6: "Terraform is the source of truth for infrastructure." |
| **Alternatives Considered** | **Pulumi** — code-as-IaC is appealing but team has Terraform experience and the HCL ecosystem is larger. **CloudFormation/CDK** — AWS-locked; CarbonSense's cloud provider is not yet committed. **Ansible** — configuration management, not infrastructure provisioning; different concern. |
| **Upgrade Policy** | Track Terraform minor releases. Pin provider versions in `.terraform.lock.hcl`. |

### 3.2 Containerization — Docker

| | |
|---|---|
| **Purpose** | Service containerization for local development, CI, and production deployment |
| **Selected Version** | **LOCKED** — Docker Engine >= 25 / Docker Compose >= 2.27 |
| **Reason for Selection** | Industry standard. Multi-stage builds for production images; Compose for local development stack (TimescaleDB, Kafka, MLflow, Temporal dev-server). |
| **Base Image** | **LOCKED** — `python:3.12-slim` for all service images. Alpine is avoided due to musl/glibc incompatibilities with scientific Python packages (NumPy, SciPy, PyTorch). |
| **Upgrade Policy** | Track Docker Engine stable releases. Rebuild base images monthly for security patches. |

### 3.3 Container Orchestration — Kubernetes

| | |
|---|---|
| **Purpose** | Production deployment and scaling |
| **Selected Version** | **PREFERRED** — Kubernetes >= 1.30 (via managed service: EKS, GKE, or AKS) |
| **Reason for Selection** | Standard orchestration for multi-service architectures. Managed service avoids control-plane operations overhead. |
| **Upgrade Policy** | Follow managed provider's supported version window. |

### 3.4 Object Storage

| | |
|---|---|
| **Purpose** | Raw uploads, generated PDFs, model artifacts (TRD v2.0 §10) |
| **Selected Version** | **LOCKED** — S3-compatible API (AWS S3, MinIO for local dev) / `boto3 >= 1.34` |
| **Upgrade Policy** | Track boto3 minor releases. |

---

## 4. Observability Stack

### 4.1 Distributed Tracing & Metrics — OpenTelemetry

| | |
|---|---|
| **Purpose** | Cross-service, cross-Temporal-workflow distributed tracing with trace ID propagation. Structured logging correlation. Metrics export. |
| **Selected Version** | **LOCKED** — `opentelemetry-api >= 1.25` / `opentelemetry-sdk >= 1.25` / `opentelemetry-instrumentation-fastapi` / `opentelemetry-exporter-otlp` |
| **Reason for Selection** | TRD v2.0 §9.5: "Structured logging with trace IDs propagated across service boundaries and across Temporal workflow executions via OpenTelemetry instrumentation — a single analysis run's trace should be reconstructable end-to-end." |
| **Alternatives Considered** | **Datadog/New Relic** — vendor-locked SaaS; higher cost at scale. **Jaeger directly** — OTel is the vendor-neutral layer; Jaeger is one possible backend. |
| **Upgrade Policy** | Track OTel SDK minor releases. OTel moves fast; pin and upgrade quarterly. |

### 4.2 Metrics Backend — Prometheus + Grafana

| | |
|---|---|
| **Purpose** | Metrics collection, dashboarding, alerting |
| **Selected Version** | **PREFERRED** — Prometheus >= 2.53 / Grafana >= 11.0 (or managed equivalent) |
| **Reason for Selection** | TRD v2.0 §10: "OpenTelemetry + a metrics/tracing backend (e.g., Prometheus/Grafana or a managed equivalent)." |
| **Alternatives Considered** | **Managed equivalents** (Grafana Cloud, Amazon Managed Prometheus) are acceptable substitutes. The choice between self-hosted and managed is an infrastructure-cost decision, not an architectural one. |
| **Upgrade Policy** | Track stable releases. |

### 4.3 Structured Logging

| | |
|---|---|
| **Purpose** | JSON-structured application logging with OTel trace ID correlation |
| **Selected Version** | **LOCKED** — `structlog >= 24.1` |
| **Reason for Selection** | Best-in-class structured logging for Python. Native processors for adding trace IDs, tenant context, and request metadata. Integrates cleanly with stdlib `logging` and OTel. |
| **Alternatives Considered** | **stdlib `logging` with JSON formatter** — functional but verbose configuration and no built-in processor pipeline. **loguru** — convenient API but less control over structured output shape and OTel integration. |
| **Upgrade Policy** | Track minor releases. |

---

## 5. Testing Stack

### 5.1 Test Framework

| | |
|---|---|
| **Purpose** | All test execution — unit, integration, security, performance, e2e |
| **Selected Version** | **LOCKED** — `pytest >= 8.0` |
| **Plugins** | `pytest-cov >= 5.0` (coverage), `pytest-asyncio >= 0.23` (async test support), `pytest-xdist >= 3.5` (parallel execution) |
| **Alternatives Considered** | **unittest** — stdlib but inferior fixture/parametrize/plugin ecosystem. **ward** — Pythonic syntax but immature plugin ecosystem. |
| **Upgrade Policy** | Track pytest minor releases. |

### 5.2 Test Markers (defined in `pyproject.toml`)

| Marker | Scope | When to Run |
|---|---|---|
| `@pytest.mark.unit` | Single-component, no external dependencies | Every PR, every CI run |
| `@pytest.mark.integration` | Cross-service, requires database | Every PR, every CI run |
| `@pytest.mark.security` | Tenant isolation fuzzer (ENG-1f) | Every data-layer PR — **same severity as a failing build** |
| `@pytest.mark.performance` | Latency benchmarks against TRD §9.1 targets | Nightly CI, pre-release |
| `@pytest.mark.e2e` | Full pipeline with golden COMBED fixture | Nightly CI, pre-release |

### 5.3 Test Standards

- **Coverage floor**: 80% line coverage for `services/`, `shared/`, `models/` — enforced in CI.
- **Golden fixture**: The COMBED dataset is seeded in `database/seeds/` and used as a known-output regression suite for e2e tests (TRD v2.0 §11.1).
- **Tenant isolation fuzzer**: Automated test suite that deliberately attempts cross-tenant reads/writes and asserts every attempt fails closed at the RLS layer (ROADMAP ENG-1f). Runs on every data-layer PR.
- **No mocking of the database in integration tests**: Integration tests hit a real TimescaleDB instance (Dockerized in CI).
- **Async tests**: Use `pytest-asyncio` with `mode = "auto"` for all async service tests.

---

## 6. Code Quality & Formatting

### 6.1 Linter — Ruff

| | |
|---|---|
| **Selected Version** | **LOCKED** — `ruff >= 0.4` |
| **Configuration** | Defined in `pyproject.toml` under `[tool.ruff]`. |
| **Line length** | 100 characters (consistent across Ruff, Black, and all editors). |
| **Rule sets** | `E`, `W` (pycodestyle), `F` (pyflakes), `I` (isort), `N` (pep8-naming), `UP` (pyupgrade), `B` (bugbear), `S` (bandit/security), `T20` (no print), `SIM` (simplify). |
| **Ignore** | `S101` — `assert` is allowed in test files. |

### 6.2 Formatter — Black

| | |
|---|---|
| **Selected Version** | **LOCKED** — `black >= 24.0` |
| **Configuration** | `line-length = 100`, `target-version = ["py311"]` in `pyproject.toml`. |
| **Relationship to Ruff** | Ruff handles linting and import sorting; Black handles formatting. Both run in pre-commit. If Ruff's formatter (`ruff format`) reaches full Black parity, consolidate to Ruff-only. |

### 6.3 Type Checker — mypy

| | |
|---|---|
| **Selected Version** | **LOCKED** — `mypy >= 1.10` |
| **Configuration** | `strict = true` in `pyproject.toml`. All new code must pass strict type checking. |
| **Upgrade Policy** | Track minor releases. |

### 6.4 Pre-Commit Hooks

Defined in `.pre-commit-config.yaml`. Every commit runs:
1. `pre-commit-hooks` — trailing whitespace, EOF fixer, YAML/TOML check, large file check, merge conflict check, private key detection.
2. `ruff` — lint with auto-fix + format.
3. `black` — format.
4. `mypy` — type check.

### 6.5 Code Standards

| Standard | Rule |
|---|---|
| Import style | Absolute imports only. No relative imports across package boundaries. `isort` enforced via Ruff. |
| Docstrings | Not required by default. Add only when the *why* is non-obvious. No multi-paragraph docstrings. |
| Type annotations | Required on all function signatures in `services/`, `shared/`, `apps/`, `models/`. |
| Error handling | Validate at system boundaries (user input, external APIs). Trust internal code and framework guarantees. No defensive `try/except` around internal calls. |
| Logging | Use `structlog` bound loggers. No `print()` statements (enforced by Ruff `T20`). |
| Secrets | Never in code, config files, or logs. Use environment variables loaded via `shared/config/`. Enforced by `detect-private-key` pre-commit hook. |

---

## 7. Package Management

| Item | Decision |
|---|---|
| **Build backend** | **LOCKED** — Hatchling (`hatchling` in `pyproject.toml` `[build-system]`). |
| **Dependency specification** | All dependencies declared in `pyproject.toml` under `[project.dependencies]` (runtime) and `[project.optional-dependencies]` (dev, test, research). |
| **Lock file** | **PREFERRED** — Generate `requirements.lock` via `pip-compile` (from `pip-tools >= 7.4`) for reproducible production builds. `pyproject.toml` is the source; the lock file is a derived artifact. |
| **Virtual environments** | **LOCKED** — `venv` (stdlib). No conda, no poetry virtualenvs. Consistent across dev, CI, and Docker builds. |
| **Dependency groups** | `[dev]` — linters, formatters, test tools. Future groups: `[ml]` — PyTorch, scikit-learn, SHAP, etc. `[research]` — PyTorch Geometric, NILM dataset loaders. Declared in `pyproject.toml`. |
| **Version pinning strategy** | **Minimum version pins** (`>=`) in `pyproject.toml` for flexibility. **Exact pins** in `requirements.lock` for reproducibility. Never use unpinned dependencies in production Docker builds. |

---

## 8. Environment Management

| Environment | Purpose | Database | Kafka | Temporal | Config Source |
|---|---|---|---|---|---|
| **Local dev** | Individual developer workstation | TimescaleDB via Docker Compose | Kafka via Docker Compose | Temporal dev-server via Docker Compose | `.env` (copied from `.env.example`) |
| **CI** | Automated testing (GitHub Actions) | TimescaleDB service container | Kafka service container | Temporal dev-server service container | CI secrets / environment variables |
| **Staging** | Pre-production validation, pilot onboarding | Managed TimescaleDB | Managed Kafka (MSK/Confluent) | Temporal Cloud (staging namespace) | Secrets manager (e.g., AWS SSM) |
| **Production** | Live tenant workloads | Managed TimescaleDB | Managed Kafka | Temporal Cloud (production namespace) | Secrets manager |

**Environment variable contract:**
- All configuration is loaded from environment variables, never from files committed to the repository.
- `.env.example` is the canonical list of required variables with placeholder values.
- `.env` is gitignored and never committed.
- `shared/config/` contains Pydantic `BaseSettings` models that validate and type-check all environment variables at application startup — a missing or malformed variable fails fast, not silently.

---

## 9. Dependency Summary Table

A consolidated view of every locked runtime dependency and its minimum version.

| Package | Min Version | Category | Epic(s) |
|---|---|---|---|
| `fastapi` | 0.115 | Web framework | ENG-5 |
| `uvicorn` | 0.30 | ASGI server | ENG-5 |
| `pydantic` | 2.7 | Data validation | All |
| `sqlalchemy` | 2.0 | ORM | ENG-1 |
| `asyncpg` | 0.29 | Async PG driver | ENG-1 |
| `alembic` | 1.13 | Migrations | ENG-1 |
| `temporalio` | 1.7 | Workflow SDK | ENG-2 |
| `confluent-kafka` | 2.5 | Kafka client | ENG-2 |
| `mlflow` | 2.15 | Model registry | ENG-6 |
| `torch` | 2.3 | Deep learning | ENG-3d, RES-3 |
| `torch-geometric` | 2.5 | GNN research | RES-3 |
| `scikit-learn` | 1.5 | ML | ENG-3d |
| `statsmodels` | 0.14 | STL decomposition | ENG-3c |
| `scipy` | 1.13 | Optimization | ENG-4 |
| `shap` | 0.45 | Explainability | ENG-3g |
| `mapie` | 0.9 | Conformal prediction | ENG-3f |
| `pymannkendall` | 1.4 | Drift detection | ENG-3e |
| `anthropic` | 0.39 | LLM SDK | ENG-5 (reporting) |
| `weasyprint` | 62 | PDF rendering | ENG-5 (reporting) |
| `structlog` | 24.1 | Logging | ENG-7 |
| `opentelemetry-api` | 1.25 | Tracing | ENG-7 |
| `opentelemetry-sdk` | 1.25 | Tracing | ENG-7 |
| `boto3` | 1.34 | S3 storage | ENG-1 |
| `pytest` | 8.0 | Testing | All |
| `pytest-cov` | 5.0 | Coverage | All |
| `pytest-asyncio` | 0.23 | Async tests | All |
| `ruff` | 0.4 | Linter | Dev |
| `black` | 24.0 | Formatter | Dev |
| `mypy` | 1.10 | Type checker | Dev |
| `pre-commit` | 3.7 | Git hooks | Dev |
| `pip-tools` | 7.4 | Lock file gen | Dev |

---

## 10. Amendment Process

1. Any change to a **LOCKED** technology requires a written ADR in `docs/ADRs/` with:
   - The specific technology being changed or added.
   - The justification, including what changed since the original decision.
   - The migration plan, including backward-compatibility impact.
   - Sign-off from the Engineering Lead.

2. Any change to a **PREFERRED** technology requires a PR comment explaining the deviation. No ADR needed unless the change affects more than one epic.

3. **OPEN** decisions must be resolved (and this document updated) before the dependent epic's first subtask begins.

4. This document is versioned alongside the codebase. Every amendment increments the version number at the top.

---

*CarbonSense TECH_STACK_LOCK.md v1.0 · Built from PRD_v2.md, TRD_v2.md, ROADMAP_v2.md,
REPOSITORY_STRUCTURE_TRACK1.md, and DATA_AND_MODEL_STRATEGY.md · 2026-06-21*