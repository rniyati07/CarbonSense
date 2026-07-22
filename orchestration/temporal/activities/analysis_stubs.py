from __future__ import annotations

import datetime
import logging
from uuid import UUID

from temporalio import activity
from temporalio.exceptions import ApplicationError

from orchestration.temporal.dto import (
    AnalysisPipelineInput,
    ConfidenceCalibrationOutput,
    DataQualityGateOutput,
    ExplainabilityOutput,
    FeatureAssemblyOutput,
    MLEnsembleOutput,
    RuleEngineOutput,
    RuleFireEvent,
    STLOutput,
)

logger = logging.getLogger(__name__)


@activity.defn
async def data_quality_gate_activity(input: AnalysisPipelineInput) -> DataQualityGateOutput:
    """Layer 1 verification (retained per approval; see services/ingestion/
    repository.py's module docstring for why this checks already-persisted
    data rather than re-running DataQualityGate.process_batch()).

    Raises a non-retryable ApplicationError when the analysis window has no
    pass/degraded data at all -- mirroring TRD v2.0 3.1's rule that "a
    quarantined-only batch does not trigger downstream analysis."
    """
    from services.ingestion.repository import DataQualityVerificationRepository
    from shared.auth.tenant_context import tenant_scope
    from shared.database import get_session_factory

    tenant_id = UUID(input.tenant_id)
    building_id = UUID(input.building_id)
    window_end = datetime.datetime.now(datetime.UTC)
    window_start = window_end - datetime.timedelta(days=input.window_days)

    factory = get_session_factory()
    async with factory() as session, tenant_scope(session, tenant_id):
        repo = DataQualityVerificationRepository(session)
        counts = await repo.get_status_counts(building_id, window_start, window_end)

    pass_count = counts.get("pass", 0)
    degraded_count = counts.get("degraded", 0)
    quarantined_count = counts.get("quarantined", 0)

    if pass_count == 0 and degraded_count == 0:
        raise ApplicationError(
            f"No pass/degraded normalized_readings for building={input.building_id} "
            f"in the last {input.window_days} days "
            f"(quarantined={quarantined_count}) -- per TRD v2.0 3.1, a "
            "quarantined-only (or empty) batch does not trigger downstream analysis.",
            non_retryable=True,
        )

    overall_status = "degraded" if degraded_count > 0 else "pass"
    return DataQualityGateOutput(
        overall_status=overall_status,
        pass_count=pass_count,
        degraded_count=degraded_count,
        quarantined_count=quarantined_count,
    )


@activity.defn
async def rule_engine_activity(input: AnalysisPipelineInput) -> RuleEngineOutput:
    """Layer 2: Domain Rule Engine (ENG-3b).

    Domain-rule findings are fully constructible immediately -- their
    ExplainabilityBundle only needs rule_citations, not top_features/
    confidence_band (see services/explainability/models.py's relaxed
    invariant for contributing_layers == {"domain_rule"}) -- so they are
    persisted here via the same ExplainabilityRepository single-INSERT
    path Root-Cause Attribution uses for ML/STL-sourced findings later,
    rather than standing up a second insert path. This is also what lets
    the existing confidence_calibration_activity's DB-polling entry point
    (calibrate_findings(), querying `findings WHERE confidence IS NULL`)
    find them.

    rule_fires is additionally returned as an explicit DTO -- Feature
    Assembly (TRD v2.0 3.4's rule_fire_indicators) needs per-(circuit, ts)
    rule-fire signals that the persisted Finding rows don't carry in a
    directly queryable shape.
    """
    from pathlib import Path

    from services.explainability.repository import ExplainabilityRepository
    from services.rules_engine.registry import RuleRegistry
    from services.rules_engine.repository import RulesEngineReadingsRepository
    from services.rules_engine.service import DomainRuleEngineService
    from shared.auth.tenant_context import tenant_scope
    from shared.database import get_session_factory

    tenant_id = UUID(input.tenant_id)
    building_id = UUID(input.building_id)
    window_end = datetime.datetime.now(datetime.UTC)
    window_start = window_end - datetime.timedelta(days=input.window_days)

    import services.rules_engine as rules_engine_pkg

    rules_dir = Path(rules_engine_pkg.__file__).resolve().parent / "rules"
    registry = RuleRegistry(str(rules_dir))
    service = DomainRuleEngineService(registry)

    factory = get_session_factory()
    async with factory() as session, tenant_scope(session, tenant_id):
        readings_repo = RulesEngineReadingsRepository(session)
        readings = await readings_repo.get_readings(
            tenant_id, building_id, window_start, window_end
        )
        circuit_types = await readings_repo.get_circuit_types(building_id)
        building_context = await readings_repo.get_building_context(building_id)

        findings = service.process_readings(
            tenant_id=tenant_id,
            building_id=building_id,
            building_context=building_context,
            readings=readings,
            circuit_types=circuit_types,
        )

        if findings:
            await ExplainabilityRepository(session).save_findings(findings)
            await session.commit()

    rule_fires = [
        RuleFireEvent(
            circuit_id=finding.circuit_id,
            ts=finding.evidence_window_start,
            rule_id=finding.explainability_bundle.rule_citations[0].rule_id,
        )
        for finding in findings
        if finding.circuit_id is not None and finding.explainability_bundle.rule_citations
    ]
    return RuleEngineOutput(findings=findings, rule_fires=rule_fires)


@activity.defn
async def stl_detection_activity(input: AnalysisPipelineInput) -> STLOutput:
    """Layer 3: STL Residual Detection (ENG-3c), run per-circuit.

    See services/stl_detection/repository.py's module docstring for why
    TimescaleCalendarRepository exposes an async fetch method rather than
    implementing the (deliberately synchronous) CalendarRepository
    Protocol directly: this activity awaits it once for the whole
    building/window, wraps the result in an InMemoryCalendarRepository,
    and injects that into STLDetectionService -- reusing
    analyse_circuit_window_with_repo() exactly as the module docstring
    documents, unchanged. STLDetectionService's own code is untouched.

    A circuit whose readings fall on a date with no building_calendar
    coverage raises CalendarLookupError (the calendar-awareness hard
    constraint -- no fallback day_type is ever fabricated). That circuit
    is skipped rather than failing the whole building's analysis, mirroring
    the graceful-degradation precedent already established by
    EnsembleServingService (catches exceptions around per-building model
    loading rather than failing every circuit over one building's issue).
    """
    from services.stl_detection.exceptions import CalendarLookupError
    from services.stl_detection.repository import (
        InMemoryCalendarRepository,
        STLReadingsRepository,
        TimescaleCalendarRepository,
    )
    from services.stl_detection.service import STLDetectionService
    from shared.auth.tenant_context import tenant_scope
    from shared.database import get_session_factory

    tenant_id = UUID(input.tenant_id)
    building_id = UUID(input.building_id)
    window_end = datetime.datetime.now(datetime.UTC)
    window_start = window_end - datetime.timedelta(days=input.window_days)

    factory = get_session_factory()
    async with factory() as session, tenant_scope(session, tenant_id):
        readings_by_circuit = await STLReadingsRepository(session).get_readings_by_circuit(
            building_id, window_start, window_end
        )
        calendar_entries = await TimescaleCalendarRepository(session).fetch_calendar_entries(
            building_id, window_start.date(), window_end.date()
        )

    calendar_repo = InMemoryCalendarRepository(calendar_entries)
    service = STLDetectionService(calendar_repo=calendar_repo)

    residuals = []
    for readings in readings_by_circuit.values():
        try:
            residuals.extend(service.analyse_circuit_window_with_repo(readings, building_id))
        except CalendarLookupError:
            continue

    return STLOutput(residuals=residuals)


@activity.defn
async def feature_assembly_activity(
    input: AnalysisPipelineInput,
    rule_output: RuleEngineOutput,
    stl_output: STLOutput,
) -> FeatureAssemblyOutput:
    """Layer 3.5: Feature Assembly (ENG-3d-1), run per-circuit.

    rule_output/stl_output arrive as explicit parameters, not DB reads --
    rule fires and STL residual fields are never persisted (see
    orchestration/temporal/dto.py's module docstring on architecture
    decision 4b); this activity is the only place they can still be read,
    since it runs directly after the parallel Rule Engine / STL Detection
    step within the same workflow execution.

    Reuses STLReadingsRepository for the same per-circuit readings both
    rule_engine_activity and stl_detection_activity already fetched --
    Feature Assembly needs the raw NormalizedReading objects themselves
    (for rolling-statistic computation), not either activity's derived
    output, so re-fetching here (rather than threading readings through
    the workflow as a third DTO) keeps the workflow's DTOs limited to
    what each layer actually produces.
    """
    from collections import defaultdict

    from models.feature_store.feature_set_v1 import FeatureSetV1STLFields
    from services.ml_ensemble.feature_assembly import FeatureAssembler
    from services.stl_detection.repository import STLReadingsRepository
    from shared.auth.tenant_context import tenant_scope
    from shared.database import get_session_factory

    tenant_id = UUID(input.tenant_id)
    building_id = UUID(input.building_id)
    window_end = datetime.datetime.now(datetime.UTC)
    window_start = window_end - datetime.timedelta(days=input.window_days)

    factory = get_session_factory()
    async with factory() as session, tenant_scope(session, tenant_id):
        readings_by_circuit = await STLReadingsRepository(session).get_readings_by_circuit(
            building_id, window_start, window_end
        )

    stl_fields_by_circuit: dict[UUID, dict[datetime.datetime, FeatureSetV1STLFields]] = defaultdict(
        dict
    )
    for residual in stl_output.residuals:
        stl_fields_by_circuit[residual.circuit_id][residual.ts] = (
            FeatureSetV1STLFields.from_stl_result(residual)
        )

    rule_fires_by_circuit: dict[UUID, dict[datetime.datetime, dict[str, bool]]] = defaultdict(dict)
    for fire in rule_output.rule_fires:
        rule_fires_by_circuit[fire.circuit_id].setdefault(fire.ts, {})[fire.rule_id] = True

    assembler = FeatureAssembler()
    features = []
    for circuit_id, readings in readings_by_circuit.items():
        features.extend(
            assembler.assemble(
                readings=readings,
                stl_fields_by_ts=stl_fields_by_circuit.get(circuit_id, {}),
                rule_fires_by_ts=rule_fires_by_circuit.get(circuit_id, {}),
            )
        )

    # ENG-6: persist so this run's features become training data. Every
    # prior consumer of FeatureAssemblyOutput used it in-memory only
    # (ml_ensemble_activity, root_cause_attribution_activity) -- nothing
    # before ENG-6 ever wrote a FeatureSetV1 row anywhere, which is exactly
    # why _fetch_training_features() (ml_ensemble_activities.py) has been a
    # TODO(ENG-6b) stub returning an empty list since ENG-3d. A fresh
    # session/tenant_scope block (rather than keeping the earlier one open
    # across the pure-compute assembly step above) matches this file's own
    # existing convention of scoping DB access tightly around each fetch.
    if features:
        from models.feature_store.repository import FeatureStoreRepository

        async with factory() as save_session, tenant_scope(save_session, tenant_id):
            await FeatureStoreRepository(save_session).save_features(features)
            await save_session.commit()

    return FeatureAssemblyOutput(features=features)


@activity.defn
async def ml_ensemble_activity(
    input: AnalysisPipelineInput,
    feature_output: FeatureAssemblyOutput,
) -> MLEnsembleOutput:
    """Layer 4: ML Ensemble scoring (ENG-3d-4).

    LocalModelRegistry (wired in Phase 1, shared/config/ml_registry.py) is
    the ModelRegistryProtocol implementation; EnsembleServingService
    already handles a missing/untrained model gracefully per-model (catches
    exceptions around load, see models/serving/ensemble_serving.py), so a
    cold-start building simply yields None-valued scores here rather than
    failing the activity. No DB session is needed -- FeatureSetV1 rows
    arrive directly via feature_output, and scoring is pure in-process
    numpy/torch inference (see ensemble_serving.py's module docstring).
    """
    from models.serving.ensemble_serving import EnsembleServingService
    from models.serving.local_registry import LocalModelRegistry
    from services.ml_ensemble.config import MLEnsembleConfig

    tenant_id = UUID(input.tenant_id)
    building_id = UUID(input.building_id)

    config = MLEnsembleConfig()
    service = EnsembleServingService(LocalModelRegistry())
    scores = service.score(
        tenant_id=tenant_id,
        building_id=building_id,
        features=feature_output.features,
        window_length_hours=config.window_length_hours,
    )
    return MLEnsembleOutput(scores=scores)


@activity.defn
async def confidence_calibration_activity(
    input: AnalysisPipelineInput,
    ml_output: MLEnsembleOutput,
) -> ConfidenceCalibrationOutput:
    """Layer 6: Confidence Calibration (ENG-3f).

    Runs both CalibrationService entry points (Phase 3 refactor) in the
    same DB transaction:
      - calibrate_findings(): unchanged, DB-polling, persists confidence
        for the domain-rule Findings rule_engine_activity already
        inserted (findings WHERE confidence IS NULL).
      - calibrate_ensemble_scores(): new, takes ml_output.scores directly,
        does NOT persist (architecture decision 4c/4d) -- no Finding
        exists yet for ML/STL-sourced anomalies at this point (Root-Cause
        Attribution creates it next). calibrated_scores is carried
        forward via ConfidenceCalibrationOutput for that activity to
        consume when building the ExplainabilityBundle's confidence_band.
    """
    from services.calibration.repository import CalibrationRepository
    from services.calibration.service import CalibrationService
    from shared.auth.tenant_context import tenant_scope
    from shared.database import get_session_factory

    tenant_id = UUID(input.tenant_id)
    building_id = UUID(input.building_id)

    factory = get_session_factory()
    async with factory() as session, tenant_scope(session, tenant_id):
        repo = CalibrationRepository(session)
        service = CalibrationService(repo)
        await service.calibrate_findings(
            tenant_id=tenant_id,
            building_id=building_id,
            correlation_id=input.correlation_id,
        )
        calibrated_scores = await service.calibrate_ensemble_scores(
            tenant_id=tenant_id,
            building_id=building_id,
            scores=ml_output.scores,
        )
        await session.commit()

    return ConfidenceCalibrationOutput(calibrated_scores=calibrated_scores)


@activity.defn
async def root_cause_attribution_activity(
    input: AnalysisPipelineInput,
    feature_output: FeatureAssemblyOutput,
    calibration_output: ConfidenceCalibrationOutput,
) -> ExplainabilityOutput:
    """Layer 7: Root-Cause Attribution (ENG-3g) -- the only INSERT point for
    ML/STL-sourced findings (see services/explainability/repository.py's
    module docstring).

    calibration_output.calibrated_scores already contains only
    ensemble_is_anomalous=True records (filtered by
    CalibrationService.calibrate_ensemble_scores(), Phase 3). For each one,
    builds a SHAP explanation against the building's trained Isolation
    Forest and assembles a Finding + ExplainabilityBundle via
    BundleAssembler -- the HARD RULE single path to
    findings.explainability_bundle, per that module's own docstring.

    A building with no trained Isolation Forest yet (cold-start, nothing
    registered) cannot produce a non-fabricated SHAP explanation --
    BundleAssembler requires non-empty top_features for ml_ensemble
    findings -- so those anomalies are skipped rather than persisted with
    fabricated attributions. This mirrors the same no-fabrication
    precedent already established by STL's calendar-awareness hard
    constraint and the Data Quality Gate's real-data-only verification.
    """
    from uuid import uuid4

    from models.feature_store.feature_set_v1 import FeatureSetV1
    from models.serving.local_registry import LocalModelRegistry
    from services.explainability.bundle_assembler import BundleAssembler
    from services.explainability.models import ConfidenceBand, EvidenceWindow
    from services.explainability.repository import ExplainabilityRepository
    from services.explainability.shap_explainer import SHAPExplainer
    from services.rules_engine.models import Finding
    from shared.auth.tenant_context import tenant_scope
    from shared.database import get_session_factory

    tenant_id = UUID(input.tenant_id)
    building_id = UUID(input.building_id)

    if not calibration_output.calibrated_scores:
        return ExplainabilityOutput(persisted_finding_ids=[], bundles=[])

    registry = LocalModelRegistry()
    try:
        if_model, _scaler, rule_ids = registry.load_isolation_forest(tenant_id, building_id)
    except Exception:
        logger.warning(
            "No trained Isolation Forest for tenant=%s building=%s -- skipping "
            "Root-Cause Attribution for %d anomalous score(s) rather than "
            "fabricating a SHAP explanation.",
            tenant_id,
            building_id,
            len(calibration_output.calibrated_scores),
        )
        return ExplainabilityOutput(persisted_finding_ids=[], bundles=[])

    feature_names = FeatureSetV1.feature_names(rule_ids)
    explainer = SHAPExplainer(tree_model=if_model, feature_names=feature_names, top_n=5)

    features_by_key = {(f.circuit_id, f.ts): f for f in feature_output.features}
    assembler = BundleAssembler()
    findings: list[Finding] = []

    for score in calibration_output.calibrated_scores:
        feature = features_by_key.get((score.circuit_id, score.ts))
        if feature is None:
            continue

        feature_row = dict(zip(feature_names, feature.to_numeric_vector(rule_ids), strict=True))
        top_features = explainer.explain(feature_row)
        bundle = assembler.assemble_ml_only(
            finding_id=uuid4(),
            top_features=top_features,
            confidence_band=ConfidenceBand(
                lower=score.confidence_lower, upper=score.confidence_upper
            ),
            evidence_window=EvidenceWindow(start=score.ts, end=score.ts),
            include_stl=feature.stl_residual_magnitude is not None,
        )

        findings.append(
            Finding(
                finding_id=bundle.finding_id,
                tenant_id=tenant_id,
                building_id=building_id,
                circuit_id=score.circuit_id,
                layer_origin="ml_ensemble",
                evidence_window_start=score.ts,
                evidence_window_end=score.ts,
                confidence=(score.confidence_lower + score.confidence_upper) / 2,
                status="open",
                explainability_bundle=bundle,
            )
        )

    if findings:
        factory = get_session_factory()
        async with factory() as session, tenant_scope(session, tenant_id):
            await ExplainabilityRepository(session).save_findings(findings)
            await session.commit()

    return ExplainabilityOutput(
        persisted_finding_ids=[f.finding_id for f in findings],
        bundles=[f.explainability_bundle for f in findings],
    )
