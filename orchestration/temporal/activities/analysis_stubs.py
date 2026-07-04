from __future__ import annotations

from temporalio import activity

from orchestration.temporal.dto import ActivityResult, AnalysisPipelineInput


@activity.defn
async def data_quality_gate_activity(input: AnalysisPipelineInput) -> ActivityResult:
    # TODO(ENG-3a): Port v1 normalization logic, stuck-at-value/dropout detection
    return ActivityResult(
        step_name="data_quality_gate",
        status="completed",
        detail=f"TODO(ENG-3a): stub for tenant={input.tenant_id}",
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
    from shared.auth.tenant_context import tenant_scope
    from shared.database import get_session_factory
    from services.calibration.repository import CalibrationRepository
    from services.calibration.service import CalibrationService

    factory = get_session_factory()
    async with factory() as session:
        async with tenant_scope(session, input.tenant_id):
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
