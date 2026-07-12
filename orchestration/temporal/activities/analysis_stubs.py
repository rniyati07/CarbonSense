from __future__ import annotations

import datetime
from uuid import UUID

from temporalio import activity
from temporalio.exceptions import ApplicationError

from orchestration.temporal.dto import ActivityResult, AnalysisPipelineInput, DataQualityGateOutput


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
async def rule_engine_activity(input: AnalysisPipelineInput) -> ActivityResult:
    # TODO(ENG-3b): Build YAML rule DSL + Python rule-evaluation service
    return ActivityResult(
        step_name="rule_engine",
        status="completed",
        detail=f"TODO(ENG-3b): stub for tenant={input.tenant_id}",
    )


@activity.defn
async def stl_detection_activity(input: AnalysisPipelineInput) -> ActivityResult:
    # TODO(ENG-3c): Implement STL decomposition with calendar-aware conditioning
    return ActivityResult(
        step_name="stl_detection",
        status="completed",
        detail=f"TODO(ENG-3c): stub for tenant={input.tenant_id}",
    )


@activity.defn
async def feature_assembly_activity(input: AnalysisPipelineInput) -> ActivityResult:
    # TODO(ENG-3d-1): Assemble feature_set_v1 from rule/STL/calendar outputs
    return ActivityResult(
        step_name="feature_assembly",
        status="completed",
        detail=f"TODO(ENG-3d-1): stub for tenant={input.tenant_id}",
    )


@activity.defn
async def ml_ensemble_activity(input: AnalysisPipelineInput) -> ActivityResult:
    # TODO(ENG-3d): Isolation Forest + Windowed Autoencoder inference
    return ActivityResult(
        step_name="ml_ensemble",
        status="completed",
        detail=f"TODO(ENG-3d): stub for tenant={input.tenant_id}",
    )


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
