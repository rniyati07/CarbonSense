# services/

Anomaly Intelligence Platform layers and the Optimization Engine.

This is the architectural centerpiece of CarbonSense — a production pipeline of eight
components (the PRD's seven layers plus the Feedback Loop). No single layer is "the
detector." A finding's confidence is a function of which layers fired and how they agree.

## Subfolders

| Folder | Layer | Purpose | Epic |
|---|---|---|---|
| `ingestion/` | Layer 1 | Data Quality Gate — validation, normalization, stuck-at/dropout detection | **ENG-3a** |
| `rules_engine/` | Layer 2 | Domain Rule Engine — ASHRAE-style deterministic FDD rules (YAML DSL) | **ENG-3b** |
| `stl_detection/` | Layer 3 | STL Residual Detection — seasonal decomposition, calendar-aware anomaly scoring | **ENG-3c** |
| `ml_ensemble/` | Layer 4 | ML Ensemble — Isolation Forest + Windowed Autoencoder | **ENG-3d** |
| `drift_detection/` | Layer 5 | Drift Detection — Mann-Kendall trend test on rolling efficiency ratio | **ENG-3e** |
| `calibration/` | Layer 6 | Confidence Calibration — conformal prediction for statistically grounded bounds | **ENG-3f** |
| `explainability/` | Layer 7 | Root-Cause Attribution — SHAP + Explainability Bundle assembly | **ENG-3g** |
| `feedback/` | Layer 8 | Feedback Loop — confirm/dismiss, retraining triggers, cross-tenant priors | **ENG-3h** |
| `optimization/` | — | Optimization Engine — load-shifting, setpoint adjustment, solar offset scenarios | **ENG-4** |
| `reporting/` | — | Reporting & PDF generation — LLM-powered narrative + WeasyPrint rendering | **ENG-5** |

## Rules

- No ML code inside API services.
- Each service owns its own data contract; none owns orchestration.
- Shared utilities belong in `shared/`, never duplicated across services.