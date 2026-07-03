"""ENG-3d — ML Ensemble Training Workflow.

Orchestrates sequential Isolation Forest and Autoencoder training for a single
(tenant, building) pair.  Both models are trained independently: IF runs first,
then AE.  A failure in one does not abort the other (each is a separate
execute_activity call with independent retry policy).

Temporal workflow design
------------------------
- One workflow execution per (tenant, building) pair per trigger.
- Both activities run sequentially (not in parallel) to avoid memory pressure
  during training on constrained worker nodes.
- Each activity has start_to_close_timeout of 60 minutes (training can be slow
  for large buildings; tune when COMBED benchmarks are available).
- heartbeat_timeout is set to 30 seconds to detect stuck activities early.

Architecture constraints
------------------------
- This workflow imports training activities through the Temporal activity import
  mechanism (with workflow.unsafe.imports_passed_through()).
- It does NOT import any training pipeline code directly — only the activities.
- Promotion logic (ENG-6) is NOT implemented here.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from orchestration.temporal.activities.ml_ensemble_activities import (
        train_autoencoder_activity,
        train_isolation_forest_activity,
    )
    from orchestration.temporal.dto import MLTrainingInput, MLTrainingResult


@workflow.defn
class MLEnsembleTrainingWorkflow:
    """Orchestrates per-building ML Ensemble training (IF + AE, ENG-3d).

    Trigger sources:
      - calendar cadence (weekly or monthly, from RetrainingWorkflow)
      - drift detection event (from DriftDetectionWorkflow)
      - feedback-volume threshold (from a future FeedbackVolumeWorkflow, ENG-6)
    """

    @workflow.run
    async def run(self, input: MLTrainingInput) -> list[MLTrainingResult]:
        """Train both models and return a list of MLTrainingResults.

        Parameters
        ----------
        input:
            MLTrainingInput.  Must include a non-empty tenant_id and building_id.

        Returns
        -------
        list[MLTrainingResult]
            Two results in order: [isolation_forest_result, autoencoder_result].
            If a model is skipped (e.g., insufficient data), its status will be
            'skipped' rather than 'completed'.
        """
        if not input.tenant_id:
            raise ApplicationError("tenant_id is required", non_retryable=True)
        if not input.building_id:
            raise ApplicationError("building_id is required", non_retryable=True)

        if_result: MLTrainingResult = await workflow.execute_activity(
            train_isolation_forest_activity,
            input,
            start_to_close_timeout=timedelta(minutes=60),
            heartbeat_timeout=timedelta(seconds=30),
        )

        ae_result: MLTrainingResult = await workflow.execute_activity(
            train_autoencoder_activity,
            input,
            start_to_close_timeout=timedelta(minutes=60),
            heartbeat_timeout=timedelta(seconds=30),
        )

        return [if_result, ae_result]
