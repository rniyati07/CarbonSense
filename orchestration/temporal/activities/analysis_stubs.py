from __future__ import annotations

import datetime
from uuid import UUID

from temporalio import activity
from temporalio.exceptions import ApplicationError

from orchestration.temporal.dto import (
    ActivityResult,
    AnalysisPipelineInput,
    DataQualityGateOutput,
    FeatureAssemblyOutput,
    MLEnsembleOutput,
    RuleEngineOutput,
    RuleFireEvent,
    STLOutput,
)


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
async def confidence_calibration_activity(input: AnalysisPipelineInput) -> ActivityResult:
    from services.calibration.repository import CalibrationRepository
    from services.calibration.service import CalibrationService
    from shared.auth.tenant_context import tenant_scope
    from shared.database import get_session_factory

    factory = get_session_factory()
    async with factory() as session, tenant_scope(session, input.tenant_id):
        repo = CalibrationRepository(session)
        service = CalibrationService(repo)
        await service.calibrate_findings(
            tenant_id=input.tenant_id,
            building_id=input.building_id,
            correlation_id=input.correlation_id,
        )
        await session.commit()

    return ActivityResult(
        step_name="confidence_calibration",
        status="completed",
        detail=f"Calibrated findings for building={input.building_id}",
    )


@activity.defn
async def root_cause_attribution_activity(input: AnalysisPipelineInput) -> ActivityResult:
    # TODO(ENG-3g): SHAP values + Explainability Bundle assembly
    return ActivityResult(
        step_name="root_cause_attribution",
        status="completed",
        detail=f"TODO(ENG-3g): stub for tenant={input.tenant_id}",
    )
