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
