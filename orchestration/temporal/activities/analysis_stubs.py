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
    # TODO(ENG-3f): Conformal prediction wrapping upstream scores
    return ActivityResult(
        step_name="confidence_calibration",
        status="completed",
        detail=f"TODO(ENG-3f): stub for tenant={input.tenant_id}",
    )


@activity.defn
async def root_cause_attribution_activity(input: AnalysisPipelineInput) -> ActivityResult:
    # TODO(ENG-3g): SHAP values + Explainability Bundle assembly
    return ActivityResult(
        step_name="root_cause_attribution",
        status="completed",
        detail=f"TODO(ENG-3g): stub for tenant={input.tenant_id}",
    )
