# models/

ML model registry, training pipelines, serving infrastructure, and feature store.

Per-tenant model management is core platform infrastructure (PRD 5.6). Models are versioned
per building using the URI convention: `models:/{tenant_id}/{building_id}/{layer}/{version}`.

## Subfolders

| Folder | Purpose | Epic |
|---|---|---|
| `registry/` | MLflow model registry configuration and utilities | **ENG-6a** |
| `training/` | Training pipeline code — Isolation Forest, Autoencoder, and (research) GNN training loops | **ENG-3d, ENG-6b** |
| `serving/` | Lightweight model-serving microservice — loads promoted versions per building from MLflow | **ENG-3d-4** |
| `feature_store/` | `feature_set_v1` definition and feature computation — the versioned contract consumed by ML Ensemble, Confidence Calibration, and GNN research | **ENG-3d-1** |

## Rules

1. No ML code inside API services.
2. Every promoted model version records: training data window, trigger, evaluation metrics, and promoting actor.
3. `feature_set_v1` is defined once in `feature_store/` — no service may maintain its own divergent copy.
4. Training is always per-tenant/per-building, never pooled across tenants.