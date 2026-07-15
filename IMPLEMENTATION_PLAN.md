# AnalysisPipelineWorkflow Architecture Completion — Implementation Plan

**Branch:** `feature/eng-2c-full-wiring` (off `develop`)
**Checkpoint commit:** `c2590d6`
**Status:** APPROVED with two changes (recorded below). Implementation in progress, committed phase by phase.

**Approved amendments:**
1. Data Quality Gate is **kept** in the workflow, not removed — replaced with a lightweight verification activity against already-persisted `normalized_readings` (§4a, revised).
2. Confidence Calibration must **not** duplicate calibration logic across two entry points — `CalibrationService` is refactored so both the existing DB-polling path and the new score-parameter path call one shared internal implementation (§4c, revised).

This plan supersedes nothing already merged to `develop`/`main` — it only wires the seven `AnalysisPipelineWorkflow` activities to the real ENG-3 services that already exist there, per the architecture-completion request.

---

## 1. Files to create

| File | Purpose |
|---|---|
| `models/serving/local_registry.py` | **Already written (checkpoint).** `LocalModelRegistry` — implements `ModelRegistryProtocol` as a thin lookup layer over MLflow's own local tracking store, which the training code already writes to. Smoke-tested end-to-end (see §6). |
| `shared/config/ml_registry.py` | `LocalModelRegistrySettings` — one field, `tracking_uri: str = "sqlite:///./local_model_registry/mlflow.db"`. (Write of this file is what triggered the pause — still pending.) |
| `services/explainability/repository.py` | `ExplainabilityRepository` — the one genuinely new persistence point in this plan. `save_finding()` INSERTs a finding with its complete bundle (rule engine already does this for domain-rule-only findings via its own repository; nothing currently INSERTs ML/STL-sourced findings — see §4). |
| `services/ingestion/repository.py` | **New (added per amendment 1).** `DataQualityVerificationRepository` — reads the already-persisted `data_quality_status` distribution for a (tenant, building, window) from `normalized_readings`. Backs the retained, lightweight `data_quality_gate_activity` (§4a, revised). |
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
| `services/calibration/service.py` | **Refactored (per amendment 2), not additive.** The calibration algorithm (fetch calibration set, check cold-start, run `ConformalPredictor`, build bands) is extracted into one shared internal method. `calibrate_findings()` (existing, DB-polling) and the new `calibrate_ensemble_scores()` (parameter-based) both become thin wrappers around it, differing only in how they obtain their input and what they do with their output. See §4c, revised. |
| `orchestration/temporal/activities/analysis_stubs.py` | Six of seven stub functions replaced with real wiring (§5). **Naming question for your review:** this file will no longer contain any stubs — I'd suggest renaming it to `analysis_activities.py` (one import site to update, in `analysis_pipeline.py`). Flagging rather than doing unilaterally since you may prefer to keep the filename stable. |
| `orchestration/temporal/workflows/analysis_pipeline.py` | Threads each activity's real DTO output into the next activity's input instead of discarding it; removes the `data_quality_gate_activity` step (§4). |
| `tests/unit/orchestration/temporal/test_analysis_pipeline.py` | Updated to mock the new repositories/registry (unit-test scope, no live DB) instead of asserting against canned stub strings. |
| `tests/unit/orchestration/temporal/test_signal_query.py` | Same update, since it also constructs `ALL_ACTIVITIES`. |

## 3. New DTOs (already written at checkpoint — `orchestration/temporal/dto.py`)

| DTO | Carries |
|---|---|
| `DataQualityGateOutput` | **New (amendment 1).** `overall_status: str` (`"pass"` / `"degraded"` / `"quarantined"`), `pass_count`, `degraded_count`, `quarantined_count` — mirrors the shape of `BatchQualityResult` from the real ingestion-time gate (`services/ingestion/models.py`) without requiring the raw batch that only exists at ingestion time. |
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

**a) Data Quality Gate — retained as a lightweight verification activity (revised per amendment 1).**
TRD §3.1's Handoff text (*"Publishes `building.data.arrived`... once a batch clears the gate at pass or degraded"*) still means the *full* `DataQualityGate.process_batch()` (raw rows, `circuit_map`) cannot run here — that data doesn't exist post-ingestion, and re-running normalization mid-pipeline isn't what this step is for. Per your instruction, `data_quality_gate_activity` is kept, redefined as a verification check against what's already persisted: `DataQualityVerificationRepository` reads the `data_quality_status` distribution for the window; the activity raises a non-retryable `ApplicationError` if there is no pass/degraded data at all (empty window or every reading quarantined) — mirroring TRD §3.1's own rule that *"a quarantined-only batch does not trigger downstream analysis"* — and otherwise returns `DataQualityGateOutput` with the pass/degraded/quarantined counts, so the workflow's `steps_completed` still reflects Layer 1 exactly as documented.

**b) Rule/STL outputs flow through the workflow as DTOs, not through the database.**
`FeatureAssembler.assemble()` needs `rule_fires_by_ts` and `stl_fields_by_ts` keyed per timestamp — neither is persisted anywhere (STL is explicitly "re-fit per window, not persisted" per TRD; Rule Engine persists coarse `Finding` rows, not a per-timestamp fire matrix). Inventing a new DB table for this intermediate signal would be new infrastructure with no spec basis. Since Temporal already durably records activity return values as part of workflow history, passing `RuleEngineOutput`/`STLOutput` directly to `feature_assembly_activity` is the minimal mechanism, not a new one.

**c) Confidence Calibration needs a new entry point, refactored to share one implementation (revised per amendment 2).**
`CalibrationService.calibrate_findings()` internally calls `self.repository.get_uncalibrated_findings()` — it queries `findings` for `confidence IS NULL` rows. But an ML-ensemble-sourced finding can't be inserted into `findings` yet at this point in the pipeline: the strict `ExplainabilityBundle` schema (added in the prior develop-integration pass) requires non-empty `top_features` for any `ml_ensemble`/`stl_residual`-involving finding, and SHAP hasn't run yet. Rather than relax that schema further, insert an invalid interim row, *or* duplicate the calibration algorithm across two methods, the cold-start-gating + `ConformalPredictor` logic is extracted into one shared internal method. `calibrate_findings()` (DB-fetch → shared logic → `save_calibrated_findings`) and the new `calibrate_ensemble_scores()` (parameter → shared logic → return, no persistence) both call it. There is exactly one implementation of the calibration algorithm in the codebase after this change, not two.

**d) The anomaly-score value fed to calibration is a proposed heuristic, not a specified one.**
`EnsembleScoreRecord` carries `if_score` and `ae_reconstruction_error` on different, incompatible scales (no combination formula is specified anywhere in the four architecture documents). I'll use `if_score` when present, falling back to `ae_reconstruction_error`, and will mark it `# PROPOSED (not yet ratified)` in code — matching the convention DATA_AND_MODEL_STRATEGY.md itself uses for exactly this kind of undocumented parameter. Only records with `ensemble_is_anomalous=True` get findings at all; non-anomalous readings don't enter this path.

**e) `TimescaleCalendarRepository` composes with, rather than replaces, `InMemoryCalendarRepository`.**
`CalendarRepository`'s Protocol method (`get_calendar_entries`) is declared synchronous, because `STLDetectionService` itself is synchronous (CPU-bound decomposition). A DB-backed implementation can't satisfy that signature without either blocking the event loop inside an async activity or making the Protocol async — the latter would change `STLDetectionService`'s own interface, out of scope. `stl_detection_activity` instead awaits `TimescaleCalendarRepository.fetch_calendar_entries()` once, then constructs an `InMemoryCalendarRepository` from the result and hands *that* to `STLDetectionService`, unchanged.

## 5. Every workflow activity, before → after

| Activity | Before | After |
|---|---|---|
| `data_quality_gate_activity` | Stub | **Kept** (revised §4a): `DataQualityVerificationRepository` → verify pass/degraded data exists for the window → `DataQualityGateOutput` |
| `rule_engine_activity` | Stub | `RulesEngineReadingsRepository` → `DomainRuleEngineService.process_readings()` → `RuleEngineOutput` |
| `stl_detection_activity` | Stub | `TimescaleCalendarRepository` + `STLReadingsRepository` → `STLDetectionService.analyse_circuit_window()` per circuit → `STLOutput` |
| `feature_assembly_activity` | Stub | `STLReadingsRepository` (reused) + `RuleEngineOutput` + `STLOutput` → `FeatureAssembler.assemble()` per circuit → `FeatureAssemblyOutput` |
| `ml_ensemble_activity` | Stub | `LocalModelRegistry` + `FeatureAssemblyOutput` → `EnsembleServingService.score()` → `MLEnsembleOutput` |
| `confidence_calibration_activity` | Already real, but DB-polling | `MLEnsembleOutput` → `CalibrationService.calibrate_ensemble_scores()` (refactored shared-core method, revised §4c) → `ConfidenceCalibrationOutput` |
| `root_cause_attribution_activity` | Stub | `LocalModelRegistry` + `RuleEngineOutput` + `MLEnsembleOutput` + `ConfidenceCalibrationOutput` → `SHAPExplainer` + `BundleAssembler` → `ExplainabilityRepository.save_finding()` (new) → `ExplainabilityOutput` |

## 6. What's already verified (checkpoint work)

- New DTOs import cleanly; Temporal serialization behavior confirmed empirically (§3).
- `RulesEngineReadingsRepository`, `TimescaleCalendarRepository`, `STLReadingsRepository` import cleanly, pass `ruff`.
- `LocalModelRegistry` — full real smoke test: trained a real `IsolationForest` via `IsolationForestTrainer` against the golden fixture corpus into a temp sqlite MLflow store, loaded it back via `LocalModelRegistry.load_isolation_forest()`, confirmed the loaded model produces real, correct `decision_function()` scores, and confirmed `ModelNotRegisteredError` raises cleanly on a miss. This also surfaced a real environment finding: the installed MLflow version rejects plain filesystem tracking outright, which is why `LocalModelRegistrySettings` defaults to `sqlite:///`, matching the existing test suite's own established workaround.

## 7. Implementation order, and why

1. **`shared/config/ml_registry.py`** — trivial, completes the Phase 4 checkpoint cleanly. *(Phase 1 commit)*
2. **`services/ingestion/repository.py` + revised `data_quality_gate_activity`** — independent of everything else; verification-only, no dependency on rule engine/STL/etc. *(Phase 1 commit, combined with step 1)*
3. **`services/explainability/repository.py`** — the one new persistence point; needs to exist before any activity can be wired end-to-end, and has no dependency on the others. *(Phase 2 commit)*
4. **`services/calibration/service.py` refactor** (shared internal method + `calibrate_ensemble_scores()`) — isolated; unblocks the calibration activity rewrite independently of the pipeline activities. *(Phase 3 commit)*
5. **Rewire `rule_engine_activity`, `stl_detection_activity`** — these two run in parallel in the workflow and have no dependency on each other or on feature assembly; wiring and unit-testing them first means Feature Assembly can be built and tested against *real* `RuleEngineOutput`/`STLOutput` shapes rather than hand-constructed fixtures. *(Phase 4 commit)*
6. **Rewire `feature_assembly_activity`** — depends on 5. *(Phase 5 commit)*
7. **Rewire `ml_ensemble_activity`** — depends on 6 and on `LocalModelRegistry` (already done). *(Phase 6 commit)*
8. **Rewire `confidence_calibration_activity`** — depends on 7 and 4. *(Phase 7 commit)*
9. **Rewire `root_cause_attribution_activity`** — depends on 8, plus `ExplainabilityRepository` (step 3). *(Phase 8 commit)*
10. **Rewrite `analysis_pipeline.py`** — only once every activity it calls has its final signature, to avoid rewriting the workflow twice. Keeps `data_quality_gate_activity` as the first step, threads every other activity's real output into the next. *(Phase 9 commit)*
11. **Unit tests** for each new repository/service method, written alongside its implementation in the same phase commit, not batched at the end.
12. **`tests/integration/test_analysis_pipeline_e2e.py`** — after the workflow rewrite, since it's the thing that proves steps 1–10 actually compose correctly against a real database. *(Phase 10 commit)*
13. **Validation sweep** (determinism, tenant isolation, service-boundary, Kafka/ML-placement checks) + full `ruff`/test run — final step before reporting back. *(Phase 11 commit)*

This order is bottom-up (data layer → individual activities → workflow → end-to-end proof) so that every piece is tested against real upstream output before the next piece is built on top of it, rather than wiring the whole workflow first and discovering a contract mismatch late.

---

**Approved. Proceeding in the order above, one commit per phase.**
