from __future__ import annotations

from dataclasses import dataclass


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
