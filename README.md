# CarbonSense

**Energy intelligence platform for building decarbonization.**

CarbonSense turns raw building meter data into a continuously updated, explainable
decarbonization program — replacing episodic, expensive energy audits with always-on
AI monitoring. The platform ingests submeter and building-level energy data, runs it
through a seven-layer anomaly intelligence pipeline, models counterfactual savings
scenarios, and produces a prioritized, ROI-ranked action plan with every finding
traceable to a defensible, root-cause explanation.

## Architecture Overview

| Layer | Technology | Purpose |
|---|---|---|
| API Gateway | FastAPI + managed gateway | Auth, rate limiting, tenant routing |
| Orchestration | Temporal | Durable, resumable pipeline execution |
| Event Backbone | Kafka | Decouples ingestion from analysis |
| Data Layer | TimescaleDB (Postgres) | Tenant-isolated relational + time-series storage |
| Model Registry | MLflow | Per-tenant/per-building versioned model management |
| Observability | OpenTelemetry | Cross-service distributed tracing |

## Repository Structure

```
apps/            → API gateway, Temporal workers, admin utilities
services/        → Anomaly Intelligence Platform layers + Optimization Engine
database/        → Alembic migrations, DDL, seeds, RLS policies
infrastructure/  → Terraform, Docker, Kubernetes, monitoring configs
orchestration/   → Temporal workflows/activities, Kafka event definitions
models/          → ML model registry, training, serving, feature store
shared/          → Cross-cutting: auth, config, logging, observability, utils
tests/           → Unit, integration, security, performance, e2e tests
docs/            → PRD, TRD, ROADMAP, ADRs, architecture diagrams
scripts/         → Bootstrap, migration, and maintenance scripts
```

See [REPOSITORY_STRUCTURE_TRACK1.md](REPOSITORY_STRUCTURE_TRACK1.md) for the full
canonical structure with epic ownership mapping.

## Quick Start

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows

# Install with dev dependencies
pip install -e ".[dev]"

# Set up pre-commit hooks
pre-commit install

# Copy environment variables
cp .env.example .env
# Edit .env with your actual values

# Run linters
make lint

# Run tests
make test
```

## Development Commands

```bash
make help            # Show all available commands
make install         # Install project + dev deps + pre-commit hooks
make lint            # Run ruff + mypy
make format          # Auto-format with ruff + black
make test            # Run all tests
make test-unit       # Run unit tests only
make test-security   # Run tenant isolation tests
make clean           # Remove caches and build artifacts
```

## Documentation

- [PRD v2.0](docs/PRD/) — Product Requirements Document
- [TRD v2.0](docs/TRD/) — Technical Requirements Document
- [ROADMAP v2.0](docs/ROADMAP/) — Engineering Roadmap (3 tracks)
- [ADRs](docs/ADRs/) — Architecture Decision Records
- [Architecture](docs/architecture/) — System diagrams and design docs

## Tracks

| Track | Scope | Key Epics |
|---|---|---|
| Track 1 — Engineering & Platform | Production SaaS platform | ENG-1 through ENG-7 |
| Track 2 — Research & Publication | Graph-aware fault localization (IEEE) | RES-1 through RES-5 |
| Track 3 — Pilot & GTM Validation | Real-world customer validation | GTM-1 through GTM-4 |

## License

Proprietary. All rights reserved.