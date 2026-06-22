# CarbonSense — Repository Structure (Track 1 Only)

**Version:** 1.0
**Scope:** Track 1 — Engineering & Platform
**Purpose:** Canonical repository structure for all ENG-* epics in the roadmap.

```text
carbonsense/

├── apps/
│   ├── api/                         # FastAPI API Gateway & public APIs (ENG-5)
│   ├── worker/                      # Temporal workers & scheduled jobs (ENG-2)
│   └── admin/                       # Internal admin utilities
│
├── services/
│   ├── ingestion/                   # ENG-3a Data Quality Gate
│   ├── rules_engine/                # ENG-3b Domain Rule Engine
│   ├── stl_detection/               # ENG-3c STL Residual Detection
│   ├── ml_ensemble/                 # ENG-3d Isolation Forest + Autoencoder
│   ├── drift_detection/             # ENG-3e Drift Detection
│   ├── calibration/                # ENG-3f Conformal Prediction
│   ├── explainability/             # ENG-3g SHAP + Explainability Bundle
│   ├── feedback/                   # ENG-3h Feedback Loop
│   ├── optimization/               # ENG-4 Optimization Engine
│   └── reporting/                  # Reporting & PDF generation
│
├── database/
│   ├── migrations/                 # Alembic migrations
│   ├── seeds/
│   ├── ddl/
│   └── policies/                   # RLS policies
│
├── infrastructure/
│   ├── terraform/                  # ENG-1c infrastructure provisioning
│   ├── docker/
│   ├── kubernetes/
│   └── monitoring/
│
├── orchestration/
│   ├── temporal/
│   │   ├── workflows/
│   │   ├── activities/
│   │   └── schedules/
│   └── events/
│       └── kafka/
│
├── models/
│   ├── registry/
│   ├── training/
│   ├── serving/
│   └── feature_store/
│
├── shared/
│   ├── auth/
│   ├── config/
│   ├── logging/
│   ├── observability/
│   ├── exceptions/
│   └── utils/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── security/
│   │   └── tenant_isolation_fuzzer/
│   ├── performance/
│   └── e2e/
│
├── docs/
│   ├── PRD/
│   ├── TRD/
│   ├── ROADMAP/
│   ├── ADRs/
│   └── architecture/
│
└── scripts/
    ├── bootstrap/
    ├── migrations/
    └── maintenance/
```

## Epic Mapping

### ENG-1
- database/
- infrastructure/terraform/
- tests/security/

### ENG-2
- orchestration/temporal/
- orchestration/events/

### ENG-3
- services/*
- models/*
- tests/unit/
- tests/integration/

### ENG-4
- services/optimization/

### ENG-5
- apps/api/
- shared/auth/
- shared/observability/

## Rules

1. All database schema changes must go through `database/migrations/`.
2. No ML code inside API services.
3. Temporal workflows live only under `orchestration/temporal/`.
4. Shared utilities belong in `shared/`, never duplicated across services.
5. Every epic must include tests.
6. Terraform is the source of truth for infrastructure.
