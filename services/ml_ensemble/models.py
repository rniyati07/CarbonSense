"""ENG-3d — ML Ensemble data transfer objects.

Pydantic models for training results and inference scores produced by the
Isolation Forest and Windowed Autoencoder pipelines.

These DTOs are the output contract between:
  - models/training/ (training pipelines)
  - models/serving/ (serving microservice)
  - orchestration/temporal/activities/ (Temporal activities)

They do NOT duplicate the NormalizedReading or FeatureSetV1 schemas
which live in services/ingestion/models.py and models/feature_store/ respectively.
"""

from __future__ import annotations

import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class TrainingArtifact(BaseModel):
    """Reference to a logged MLflow artifact for one model component.

    Carries enough information for the serving service to locate and load
    the model and its associated scaler.
    """

    run_id: str = Field(description="MLflow run ID that produced this artifact.")
    artifact_path: str = Field(description="Relative artifact path within the MLflow run.")
    artifact_uri: str = Field(description="Full artifact URI (file:// or s3:// etc.).")


class TrainingRunResult(BaseModel):
    """Result of a single per-tenant/per-building training run.

    Both the model and the scaler are logged as separate artifacts within
    the same MLflow run so they travel together through the registry.

    Registry URI convention per TRD §6.1:
        models:/{tenant_id}/{building_id}/ml_ensemble/{version}
    """

    tenant_id: UUID
    building_id: UUID
    model_type: str = Field(description="'isolation_forest' or 'autoencoder'.")
    trained_at: datetime.datetime = Field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC),
    )
    training_trigger: str = Field(
        default="calendar",
        description="calendar | drift | feedback_volume",
    )
    mlflow_run_id: str
    model_artifact: TrainingArtifact
    scaler_artifact: TrainingArtifact
    rule_ids_used: list[str] = Field(
        default_factory=list,
        description=(
            "Ordered list of rule_ids whose indicators were included in the "
            "feature vector at training time.  The scaler was fit on this "
            "ordering — serving MUST use the same ordering."
        ),
    )
    n_training_samples: int = Field(ge=0)
    metrics: dict[str, float] = Field(default_factory=dict)


class IsolationForestScore(BaseModel):
    """Isolation Forest anomaly score for a single feature row."""

    tenant_id: UUID
    circuit_id: UUID
    ts: datetime.datetime
    if_score: float = Field(
        description=(
            "Raw Isolation Forest decision function output.  "
            "Negative values indicate anomalies; the more negative, the more anomalous.  "
            "sklearn convention: score < 0 → anomaly."
        ),
    )
    is_anomalous: bool = Field(
        description="True when if_score < 0 (i.e., the model predicts this point as an outlier).",
    )


class AutoencoderWindowScore(BaseModel):
    """Autoencoder reconstruction error for a single sliding window."""

    tenant_id: UUID
    circuit_id: UUID
    window_start: datetime.datetime
    window_end: datetime.datetime
    reconstruction_error: float = Field(
        ge=0.0,
        description="Mean squared reconstruction error for this window.",
    )
    is_anomalous: bool = Field(
        description=(
            "True when reconstruction_error exceeds the per-building anomaly threshold "
            "(set at training time as the configured reconstruction_threshold_percentile "
            "of the training-set reconstruction errors)."
        ),
    )


class EnsembleScoreRecord(BaseModel):
    """Combined anomaly assessment from both ensemble members for one reading.

    This is the primary output of the serving microservice (ENG-3d-4) and
    the input to Confidence Calibration (ENG-3f).
    """

    tenant_id: UUID
    circuit_id: UUID
    ts: datetime.datetime

    if_score: float | None = Field(
        default=None,
        description="Isolation Forest raw decision score (None if model not available).",
    )
    if_is_anomalous: bool = Field(
        default=False,
        description="Isolation Forest anomaly flag.",
    )

    ae_reconstruction_error: float | None = Field(
        default=None,
        ge=0.0,
        description="Autoencoder window reconstruction error (None if model not available).",
    )
    ae_is_anomalous: bool = Field(
        default=False,
        description="Autoencoder anomaly flag.",
    )

    ensemble_is_anomalous: bool = Field(
        default=False,
        description="True when either ensemble member flags this reading as anomalous.",
    )

    low_data_quality: bool = Field(
        default=False,
        description="Propagated from FeatureSetV1.low_data_quality.",
    )
