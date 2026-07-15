from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from uuid import UUID

from models.feature_store.feature_set_v1 import FeatureSetV1
from services.calibration.dto import CalibratedScore
from services.explainability.models import ExplainabilityBundle
from services.ml_ensemble.models import EnsembleScoreRecord
from services.rules_engine.models import Finding
from services.stl_detection.models import STLResidualResult


@dataclass(frozen=True)
class HelloWorldInput:
    name: str


@dataclass(frozen=True)
class HelloWorldResult:
    greeting: str


@dataclass(frozen=True)
class AnalysisPipelineInput:
    tenant_id: str
    building_id: str
    correlation_id: str
    # ENG-2c-wiring addition: every real repository fetch in this pipeline
    # needs an explicit analysis window, which nothing previously supplied.
    # Defaulted so every existing caller/test constructing AnalysisPipelineInput
    # without this field keeps working unchanged.
    window_days: int = 30


# --------------------------------------------------------------------------
# ENG-2c-wiring: explicit inter-activity DTOs (Analysis Pipeline architecture
# completion). Each stage's real output becomes the next stage's input,
# instead of being discarded. Pydantic model fields (Finding, FeatureSetV1,
# STLResidualResult, ExplainabilityBundle, EnsembleScoreRecord) round-trip
# through Temporal's default data converter with correct type reconstruction
# on the receiving side -- verified directly against this repo's installed
# temporalio version before relying on it here, since the wrong assumption
# would fail silently until workflow execution.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class DataQualityGateOutput:
    """Result of the retained, lightweight Data Quality Gate verification
    (see services/ingestion/repository.py's module docstring for why this
    checks already-persisted data rather than re-running
    DataQualityGate.process_batch()). Mirrors BatchQualityResult's status
    fields (services/ingestion/models.py) without the raw-row fields that
    don't exist at this point in the pipeline.
    """

    overall_status: str  # "pass" | "degraded" | "quarantined"
    pass_count: int = 0
    degraded_count: int = 0
    quarantined_count: int = 0


@dataclass(frozen=True)
class RuleFireEvent:
    """One (circuit, timestamp, rule) firing -- the granular signal
    Feature Assembly needs (TRD v2.0 3.4's `rule_fire_indicators`) that
    DomainRuleEngineService.process_readings()'s `list[Finding]` return
    value doesn't carry directly. Derived by the activity from the real
    Finding list post-hoc (each rule-fired Finding's evidence window is a
    single point in time) -- no change to rules_engine's own service code.
    """

    circuit_id: UUID
    ts: datetime.datetime
    rule_id: str


@dataclass(frozen=True)
class RuleEngineOutput:
    findings: list[Finding]
    rule_fires: list[RuleFireEvent]


@dataclass(frozen=True)
class STLOutput:
    residuals: list[STLResidualResult]


@dataclass(frozen=True)
class FeatureAssemblyOutput:
    features: list[FeatureSetV1]


@dataclass(frozen=True)
class MLEnsembleOutput:
    scores: list[EnsembleScoreRecord]


@dataclass(frozen=True)
class ConfidenceCalibrationOutput:
    # CalibratedScore is owned by services.calibration.dto (the service that
    # produces it), not defined here -- services must not depend on the
    # orchestration layer, so this DTO imports from the service, matching
    # the direction every other field on this page already uses
    # (Finding, FeatureSetV1, etc. are all owned by their services too).
    calibrated_scores: list[CalibratedScore] = field(default_factory=list)


@dataclass(frozen=True)
class ExplainabilityOutput:
    """IDs of findings persisted with a complete ExplainabilityBundle this run."""

    persisted_finding_ids: list[UUID] = field(default_factory=list)
    bundles: list[ExplainabilityBundle] = field(default_factory=list)


@dataclass
class AnalysisPipelineStatus:
    workflow_id: str
    current_step: str
    steps_completed: list[str]
    is_waiting_for_human_review: bool


@dataclass(frozen=True)
class HumanReviewSignal:
    reviewer_id: str
    action: str  # "approved" | "rejected"
    comment: str = ""


@dataclass(frozen=True)
class ActivityResult:
    step_name: str
    status: str  # "completed" | "skipped"
    detail: str = ""


@dataclass(frozen=True)
class DriftDetectionInput:
    tenant_id: str
    building_id: str


@dataclass(frozen=True)
class RetrainingInput:
    tenant_id: str
    building_id: str
    trigger: str = "calendar"  # "calendar" | "drift" | "feedback_volume"


@dataclass(frozen=True)
class MLTrainingInput:
    """Input DTO for ML Ensemble training Temporal activities (ENG-3d).

    Uses str (not UUID) for Temporal serialisation compatibility.
    The training activities convert back to UUID before calling the trainer.
    """

    tenant_id: str
    building_id: str
    building_type: str = "unknown"
    trigger: str = "calendar"  # "calendar" | "drift" | "feedback_volume"
    mlflow_tracking_uri: str = ""


@dataclass(frozen=True)
class MLTrainingResult:
    """Result DTO returned by ML Ensemble training Temporal activities (ENG-3d)."""

    tenant_id: str
    building_id: str
    model_type: str  # "isolation_forest" | "autoencoder"
    mlflow_run_id: str
    model_artifact_uri: str
    scaler_artifact_uri: str
    n_training_samples: int
    status: str = "completed"  # "completed" | "skipped" | "failed"
    detail: str = ""
