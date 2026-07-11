# AnalysisPipelineWorkflow Architecture Completion — Implementation Plan

**Branch:** `feature/eng-2c-full-wiring` (off `develop`)
**Checkpoint commit:** `c2590d6`
**Status:** Awaiting approval. Nothing beyond the checkpoint has been written.

This plan supersedes nothing already merged to `develop`/`main` — it only wires the seven `AnalysisPipelineWorkflow` activities to the real ENG-3 services that already exist there, per the architecture-completion request.

---

## 1. Files to create

| File | Purpose |
|---|---|
| `models/serving/local_registry.py` | **Already written (checkpoint).** `LocalModelRegistry` — implements `ModelRegistryProtocol` as a thin lookup layer over MLflow's own local tracking store, which the training code already writes to. Smoke-tested end-to-end (see §6). |
| `shared/config/ml_registry.py` | `LocalModelRegistrySettings` — one field, `tracking_uri: str = "sqlite:///./local_model_registry/mlflow.db"`. (Write of this file is what triggered the pause — still pending.) |
| `services/explainability/repository.py` | `ExplainabilityRepository` — the one genuinely new persistence point in this plan. `save_finding()` INSERTs a finding with its complete bundle (rule engine already does this for domain-rule-only findings via its own repository; nothing currently INSERTs ML/STL-sourced findings — see §4). |
| `tests/unit/services/rules_engine/test_repository.py` | Unit tests for `RulesEngineReadingsRepository` against a mocked `AsyncSession` (same mocking style as existing calibration/feedback tests). |
| `tests/unit/services/stl_detection/test_repository.py` | Unit tests for `TimescaleCalendarRepository` and `STLReadingsRepository`, mocked session. |
| `tests/unit/models/serving/test_local_registry.py` | Unit test for `LocalModelRegistry`, formalizing the manual smoke test already run: train a real `IsolationForestTrainer` model against the golden fixture into a temp sqlite tracking store, load it back, assert real scores, assert `ModelNotRegisteredError` on a miss. |
| `tests/unit/services/explainability/test_repository.py` | Unit tests for `ExplainabilityRepository.save_finding()`, mocked session. |
| `tests/integration/test_analysis_pipeline_e2e.py` | The Phase 6 deliverable: Raw Data → Rule Engine → STL → Feature Assembly → ML Ensemble → Confidence → Explainability, executed for real against a live TimescaleDB (marked `@pytest.mark.integration`, matching the existing `tests/integration/test_ml_ensemble_pipeline.py` / `test_rules_engine.py` / `test_stl_detection_pipeline.py` convention — these require the same real-DB CI job that already exists, not a new one). |

## 2. Existing files to modify

| File | Change |
|---|---|
| `orchestration/temporal/dto.py` | **Already written (checkpoint).** New DTOs (§3) + defaulted `window_days` field on `AnalysisPipelineInput`. |
| `services/rules_engine/repository.py` | **Already written (checkpoint).** Added `RulesEngineReadingsRepository`. Existing classes (`FindingRepository`, `DatabaseFindingRepository`, `RuleRegistryRepository`, etc.) untouched. |
| `services/stl_detection/repository.py` | **Already written (checkpoint).** Added `TimescaleCalendarRepository`, `STLReadingsRepository`. Existing `InMemoryCalendarRepository` untouched. |
| `services/calibration/service.py` | Add **one new method**, `calibrate_scores(tenant_id, building_id, scores: list[EnsembleScoreRecord]) -> list[CalibratedScore]`. Reuses the existing `ConformalPredictor`, `get_calibration_set()`, and `get_building_cold_start_flag()` calls verbatim — the only change is the score *source* (a parameter instead of `get_uncalibrated_findings()`'s DB query). `calibrate_findings()` (the existing DB-polling method) is left in place, untouched, unused by the new wiring. See §4 for why this is needed instead of reusing `calibrate_findings()` directly. |
| `orchestration/temporal/activities/analysis_stubs.py` | Six of seven stub functions replaced with real wiring (§5). **Naming question for your review:** this file will no longer contain any stubs — I'd suggest renaming it to `analysis_activities.py` (one import site to update, in `analysis_pipeline.py`). Flagging rather than doing unilaterally since you may prefer to keep the filename stable. |
| `orchestration/temporal/workflows/analysis_pipeline.py` | Threads each activity's real DTO output into the next activity's input instead of discarding it; removes the `data_quality_gate_activity` step (§4). |
| `tests/unit/orchestration/temporal/test_analysis_pipeline.py` | Updated to mock the new repositories/registry (unit-test scope, no live DB) instead of asserting against canned stub strings. |
| `tests/unit/orchestration/temporal/test_signal_query.py` | Same update, since it also constructs `ALL_ACTIVITIES`. |

## 3. New DTOs (already written at checkpoint — `orchestration/temporal/dto.py`)

| DTO | Carries |
|---|---|
| `RuleFireEvent` | One `(circuit_id, ts, rule_id)` firing — derived from `DomainRuleEngineService`'s real `list[Finding]` output, not a service change. |
| `RuleEngineOutput` | `findings: list[Finding]`, `rule_fires: list[RuleFireEvent]` |
| `STLOutput` | `residuals: list[STLResidualResult]` |
| `FeatureAssemblyOutput` | `features: list[FeatureSetV1]` |
| `MLEnsembleOutput` | `scores: list[EnsembleScoreRecord]` |
| `CalibratedScore` | Per-reading confidence band, keyed by `(circuit_id, ts)` for downstream matching |
| `ConfidenceCalibrationOutput` | `calibrated_scores: list[CalibratedScore]` |
| `ExplainabilityOutput` | `persisted_finding_ids: list[UUID]`, `bundles: list[ExplainabilityBundle]` |

**Verified, not assumed:** Pydantic model fields (`Finding`, `FeatureSetV1`, `STLResidualResult`, `ExplainabilityBundle`, `EnsembleScoreRecord`), `list[Model]`, and raw `UUID` fields all round-trip correctly through this repo's installed `temporalio` default data converter, with correct type reconstruction on decode — checked empirically against the actual library before designing DTOs around it, not assumed from documentation.

## 4. Architecture decisions requiring your attention

These are the four points in this plan that involved a real design choice rather than mechanical wiring. Flagging each explicitly, per the instruction to explain deviations.

**a) Data Quality Gate — removed from the workflow, not wired.**
TRD §3.1's Handoff text: *"Publishes `building.data.arrived` to the event backbone once a batch clears the gate at pass or degraded"* — and that event is what starts this workflow (TRD §1.2). The gate has therefore already run by the time `AnalysisPipelineWorkflow` executes; there is no raw pre-normalization batch available inside the workflow to re-run it against. Per your instruction, this activity is removed rather than stubbed further, with this citation recorded in the workflow's docstring.

**b) Rule/STL outputs flow through the workflow as DTOs, not through the database.**
`FeatureAssembler.assemble()` needs `rule_fires_by_ts` and `stl_fields_by_ts` keyed per timestamp — neither is persisted anywhere (STL is explicitly "re-fit per window, not persisted" per TRD; Rule Engine persists coarse `Finding` rows, not a per-timestamp fire matrix). Inventing a new DB table for this intermediate signal would be new infrastructure with no spec basis. Since Temporal already durably records activity return values as part of workflow history, passing `RuleEngineOutput`/`STLOutput` directly to `feature_assembly_activity` is the minimal mechanism, not a new one.

**c) Confidence Calibration needs a new method, not just new wiring.**
`CalibrationService.calibrate_findings()` internally calls `self.repository.get_uncalibrated_findings()` — it queries `findings` for `confidence IS NULL` rows. But an ML-ensemble-sourced finding can't be inserted into `findings` yet at this point in the pipeline: the strict `ExplainabilityBundle` schema (added in the prior develop-integration pass) requires non-empty `top_features` for any `ml_ensemble`/`stl_residual`-involving finding, and SHAP hasn't run yet. Rather than relax that schema further or insert an invalid interim row, `calibrate_scores()` is a new method that reuses the exact same `ConformalPredictor`/cold-start-gating logic, taking `EnsembleScoreRecord`s as a parameter instead of querying the DB. `calibrate_findings()` itself is untouched.

**d) The anomaly-score value fed to calibration is a proposed heuristic, not a specified one.**
`EnsembleScoreRecord` carries `if_score` and `ae_reconstruction_error` on different, incompatible scales (no combination formula is specified anywhere in the four architecture documents). I'll use `if_score` when present, falling back to `ae_reconstruction_error`, and will mark it `# PROPOSED (not yet ratified)` in code — matching the convention DATA_AND_MODEL_STRATEGY.md itself uses for exactly this kind of undocumented parameter. Only records with `ensemble_is_anomalous=True` get findings at all; non-anomalous readings don't enter this path.

**e) `TimescaleCalendarRepository` composes with, rather than replaces, `InMemoryCalendarRepository`.**
`CalendarRepository`'s Protocol method (`get_calendar_entries`) is declared synchronous, because `STLDetectionService` itself is synchronous (CPU-bound decomposition). A DB-backed implementation can't satisfy that signature without either blocking the event loop inside an async activity or making the Protocol async — the latter would change `STLDetectionService`'s own interface, out of scope. `stl_detection_activity` instead awaits `TimescaleCalendarRepository.fetch_calendar_entries()` once, then constructs an `InMemoryCalendarRepository` from the result and hands *that* to `STLDetectionService`, unchanged.

## 5. Every workflow activity, before → after

| Activity | Before | After |
|---|---|---|
| `data_quality_gate_activity` | Stub | **Removed** (§4a) |
| `rule_engine_activity` | Stub | `RulesEngineReadingsRepository` → `DomainRuleEngineService.process_readings()` → `RuleEngineOutput` |
| `stl_detection_activity` | Stub | `TimescaleCalendarRepository` + `STLReadingsRepository` → `STLDetectionService.analyse_circuit_window()` per circuit → `STLOutput` |
| `feature_assembly_activity` | Stub | `STLReadingsRepository` (reused) + `RuleEngineOutput` + `STLOutput` → `FeatureAssembler.assemble()` per circuit → `FeatureAssemblyOutput` |
| `ml_ensemble_activity` | Stub | `LocalModelRegistry` + `FeatureAssemblyOutput` → `EnsembleServingService.score()` → `MLEnsembleOutput` |
| `confidence_calibration_activity` | Already real, but DB-polling | `MLEnsembleOutput` → `CalibrationService.calibrate_scores()` (new method, §4c) → `ConfidenceCalibrationOutput` |
| `root_cause_attribution_activity` | Stub | `LocalModelRegistry` + `RuleEngineOutput` + `MLEnsembleOutput` + `ConfidenceCalibrationOutput` → `SHAPExplainer` + `BundleAssembler` → `ExplainabilityRepository.save_finding()` (new) → `ExplainabilityOutput` |

## 6. What's already verified (checkpoint work)

- New DTOs import cleanly; Temporal serialization behavior confirmed empirically (§3).
- `RulesEngineReadingsRepository`, `TimescaleCalendarRepository`, `STLReadingsRepository` import cleanly, pass `ruff`.
- `LocalModelRegistry` — full real smoke test: trained a real `IsolationForest` via `IsolationForestTrainer` against the golden fixture corpus into a temp sqlite MLflow store, loaded it back via `LocalModelRegistry.load_isolation_forest()`, confirmed the loaded model produces real, correct `decision_function()` scores, and confirmed `ModelNotRegisteredError` raises cleanly on a miss. This also surfaced a real environment finding: the installed MLflow version rejects plain filesystem tracking outright, which is why `LocalModelRegistrySettings` defaults to `sqlite:///`, matching the existing test suite's own established workaround.

## 7. Implementation order, and why

1. **`shared/config/ml_registry.py`** — trivial, unblocks nothing else technically but completes the Phase 4 checkpoint cleanly.
2. **`services/explainability/repository.py`** — the one new persistence point; needs to exist before any activity can be wired end-to-end, and has no dependency on the others.
3. **`services/calibration/service.py`'s `calibrate_scores()`** — small, isolated addition; unblocks the calibration activity rewrite independently of the pipeline activities.
4. **Rewire `rule_engine_activity`, `stl_detection_activity`** — these two run in parallel in the workflow and have no dependency on each other or on feature assembly; wiring and unit-testing them first means Feature Assembly can be built and tested against *real* `RuleEngineOutput`/`STLOutput` shapes rather than hand-constructed fixtures.
5. **Rewire `feature_assembly_activity`** — depends on 4.
6. **Rewire `ml_ensemble_activity`** — depends on 5 and on `LocalModelRegistry` (already done).
7. **Rewire `confidence_calibration_activity`** — depends on 6 and 3.
8. **Rewire `root_cause_attribution_activity`** — depends on 7, plus `ExplainabilityRepository` (step 2).
9. **Rewrite `analysis_pipeline.py`** — only once every activity it calls has its final signature, to avoid rewriting the workflow twice.
10. **Unit tests** for each new repository/service method, written alongside its implementation (steps 1–8), not batched at the end.
11. **`tests/integration/test_analysis_pipeline_e2e.py`** — last, since it's the thing that proves steps 1–9 actually compose correctly against a real database.
12. **Phase 5 validation sweep** (determinism, tenant isolation, service-boundary, Kafka/ML-placement checks) + full `ruff`/test run — final step before reporting back.

This order is bottom-up (data layer → individual activities → workflow → end-to-end proof) so that every piece is tested against real upstream output before the next piece is built on top of it, rather than wiring the whole workflow first and discovering a contract mismatch late.

---

**Waiting for your approval before touching any file beyond this plan.**
