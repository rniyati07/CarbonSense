"""ENG-6c/6e — training summary / before-vs-after benchmark reports.

format_training_summary() renders a TrainAndEvaluateSummary
(pipelines.training.train_and_evaluate) as a human-readable report:
what was trained, on how much data, whether it was promoted or held, and
why. benchmark_against_previous_champion() is the "before vs. after"
half (ENG-6e: "Benchmark models before and after retraining") -- it reads
the previously-promoted version's own logged metrics straight out of
MLflow (no separate benchmark-tracking store; the training run itself
already recorded everything needed) and diffs them against the new
candidate's metrics.
"""

from __future__ import annotations

import dataclasses
import logging

from mlflow import MlflowClient
from mlflow.exceptions import MlflowException

from models.registry.mlflow_registry import MLflowModelRegistry
from models.registry.register import registered_model_name
from pipelines.training.train_and_evaluate import ModelTrainingOutcome, TrainAndEvaluateSummary

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class MetricComparison:
    model_type: str
    previous_version: str | None
    previous_metrics: dict[str, float]
    candidate_metrics: dict[str, float]
    delta: dict[str, float]


def benchmark_against_previous_champion(
    outcome: ModelTrainingOutcome, registry: MLflowModelRegistry
) -> MetricComparison:
    """Compares outcome.result.metrics against whatever version was the
    champion *before* this training run's registration. Metrics present
    in only one of the two runs are omitted from delta (nothing to
    subtract against)."""
    tenant_id, building_id = outcome.result.tenant_id, outcome.result.building_id
    model_type = outcome.result.model_type

    previous_version = registry.get_previous_version(tenant_id, building_id, model_type)
    previous_metrics: dict[str, float] = {}
    if previous_version is not None:
        try:
            client = MlflowClient(tracking_uri=registry.tracking_uri)
            name = registered_model_name(tenant_id, building_id, model_type)
            model_version = client.get_model_version(name, previous_version)
            if model_version.run_id is not None:
                previous_metrics = dict(client.get_run(model_version.run_id).data.metrics)
        except MlflowException:
            logger.warning(
                "benchmark_against_previous_champion: could not load metrics for "
                "prior version=%s of %s/%s/%s",
                previous_version,
                tenant_id,
                building_id,
                model_type,
            )

    candidate_metrics = outcome.result.metrics
    delta = {
        key: candidate_metrics[key] - previous_metrics[key]
        for key in candidate_metrics
        if key in previous_metrics
    }

    return MetricComparison(
        model_type=model_type,
        previous_version=previous_version,
        previous_metrics=previous_metrics,
        candidate_metrics=candidate_metrics,
        delta=delta,
    )


def format_training_summary(summary: TrainAndEvaluateSummary) -> str:
    lines = [
        "=== CarbonSense Training Summary ===",
        f"tenant_id:        {summary.tenant_id}",
        f"building_id:      {summary.building_id}",
        f"trigger:          {summary.trigger}",
        f"features_used:    {summary.n_features_used}",
    ]

    if summary.skipped_reason is not None:
        lines.append(f"SKIPPED: {summary.skipped_reason}")
        return "\n".join(lines)

    for outcome in summary.outcomes:
        result, decision = outcome.result, outcome.decision
        lines.append("")
        lines.append(f"--- {result.model_type} ---")
        lines.append(f"  n_training_samples: {result.n_training_samples}")
        lines.append(f"  mlflow_run_id:      {result.mlflow_run_id}")
        lines.append(f"  registered_version: {result.registered_version}")
        for key, value in result.metrics.items():
            lines.append(f"  metric.{key}: {value:.4f}")
        outcome_word = (
            "PROMOTED"
            if decision.approved
            else ("HELD FOR HUMAN REVIEW" if decision.requires_human_review else "REJECTED")
        )
        lines.append(f"  outcome: {outcome_word} -- {decision.reason}")

    return "\n".join(lines)
