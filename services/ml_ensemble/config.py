"""ENG-3d — ML Ensemble configuration.

All hyperparameters and thresholds for the Isolation Forest and Windowed
Autoencoder are centralised here.  Service code and test code MUST import
constants from this module — never hardcode a numeric value elsewhere.

Key design decisions
--------------------
contamination (default 0.05 = 5%)
    The expected proportion of anomalies in training data for Isolation Forest.
    DATA_AND_MODEL_STRATEGY §5.1 specifies this as a PROPOSED default of 5%.
    EMPIRICAL VALIDATION REQUIRED: this parameter directly trades precision
    against recall and must be calibrated against the COMBED golden fixture
    (ENG-6c) and real pilot data (GTM-2a) before production deployment.
    Per-building-type overrides are supported via building_type_contamination_overrides.

window_length_hours (default 24)
    The length in hours of the sliding window fed to the Autoencoder.
    DATA_AND_MODEL_STRATEGY §5.2 specifies 24–48 hours as the range.
    EMPIRICAL VALIDATION REQUIRED: validate against COMBED anomaly duration
    statistics before locking this value for production deployment.

autoencoder_latent_dim (default 8)
    Bottleneck dimension of the Autoencoder.  Smaller = stronger compression =
    higher sensitivity to pattern anomalies.  Larger = more permissive reconstruction.
    EMPIRICAL VALIDATION REQUIRED: tune against the COMBED golden fixture.

mlflow_experiment_name
    MLflow experiment name for logging training runs.  The full registry path
    per TRD §6.1 is models:/{tenant_id}/{building_id}/ml_ensemble/{version}.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class MLEnsembleConfig(BaseModel):
    """Configuration for the ML Ensemble (Isolation Forest + Windowed Autoencoder).

    All numeric thresholds MUST be sourced from this model.
    """

    # ------------------------------------------------------------------ #
    # Isolation Forest parameters
    # ------------------------------------------------------------------ #

    contamination: float = Field(
        default=0.05,
        gt=0.0,
        lt=0.5,
        description=(
            "Expected proportion of anomalies in training data.  "
            "PROPOSED DEFAULT: 5% (DATA_AND_MODEL_STRATEGY §5.1).  "
            "EMPIRICAL VALIDATION REQUIRED against the COMBED golden fixture "
            "(ENG-6c) and real pilot data (GTM-2a) before production deployment.  "
            "Per-building-type overrides available via building_type_contamination_overrides."
        ),
    )

    n_estimators: int = Field(
        default=100,
        ge=10,
        description=(
            "Number of trees in the Isolation Forest.  "
            "100 is the sklearn default and a reasonable starting point.  "
            "IMPLEMENTATION DEFAULT — tune empirically."
        ),
    )

    if_random_state: int = Field(
        default=42,
        description="Random seed for Isolation Forest reproducibility.",
    )

    building_type_contamination_overrides: dict[str, float] = Field(
        default_factory=dict,
        description=(
            "Per-building-type contamination overrides.  "
            "Keys are building_type strings (e.g. 'office', 'retail', 'industrial').  "
            "Values override the global contamination for buildings of that type.  "
            "EMPIRICAL VALIDATION REQUIRED per building type before production use."
        ),
    )

    # ------------------------------------------------------------------ #
    # Windowed Autoencoder parameters
    # ------------------------------------------------------------------ #

    window_length_hours: int = Field(
        default=24,
        ge=4,
        le=168,
        description=(
            "Number of hourly readings per sliding window fed to the Autoencoder.  "
            "PROPOSED DEFAULT: 24 hours (DATA_AND_MODEL_STRATEGY §5.2 specifies 24–48 hours).  "
            "EMPIRICAL VALIDATION REQUIRED: validate against COMBED anomaly duration "
            "statistics before locking this value."
        ),
    )

    autoencoder_hidden_dims: list[int] = Field(
        default_factory=lambda: [64, 32],
        description=(
            "Hidden layer dimensions for the Autoencoder encoder.  "
            "Decoder mirrors these in reverse order.  "
            "IMPLEMENTATION DEFAULT — tune against the golden fixture."
        ),
    )

    autoencoder_latent_dim: int = Field(
        default=8,
        ge=2,
        description=(
            "Bottleneck (latent) dimension of the Autoencoder.  "
            "Smaller values = stronger compression = higher sensitivity to pattern anomalies.  "
            "EMPIRICAL VALIDATION REQUIRED."
        ),
    )

    autoencoder_epochs: int = Field(
        default=50,
        ge=1,
        description=(
            "Maximum training epochs for the Autoencoder.  "
            "IMPLEMENTATION DEFAULT — stop early via early stopping patience if needed."
        ),
    )

    autoencoder_batch_size: int = Field(
        default=32,
        ge=1,
        description="Mini-batch size for Autoencoder training.",
    )

    autoencoder_learning_rate: float = Field(
        default=1e-3,
        gt=0.0,
        description="Adam learning rate for Autoencoder training.",
    )

    autoencoder_reconstruction_threshold_percentile: float = Field(
        default=95.0,
        gt=50.0,
        le=99.9,
        description=(
            "Percentile of training-set reconstruction errors used as the anomaly "
            "threshold for the Autoencoder.  Windows above this threshold are flagged.  "
            "EMPIRICAL VALIDATION REQUIRED — 95th percentile is a starting point."
        ),
    )

    ae_random_state: int = Field(
        default=42,
        description="Random seed for Autoencoder training reproducibility (torch manual_seed).",
    )

    # ------------------------------------------------------------------ #
    # Serving / inference
    # ------------------------------------------------------------------ #

    max_inference_batch_size: int = Field(
        default=512,
        ge=1,
        description=(
            "Maximum number of feature rows processed in a single inference call.  "
            "Larger batches are split automatically."
        ),
    )

    # ------------------------------------------------------------------ #
    # MLflow
    # ------------------------------------------------------------------ #

    mlflow_experiment_name: str = Field(
        default="carbonsense_ml_ensemble",
        description=(
            "MLflow experiment name for training runs.  "
            "The registry path follows TRD §6.1: "
            "models:/{tenant_id}/{building_id}/ml_ensemble/{version}."
        ),
    )

    def contamination_for_building_type(self, building_type: str) -> float:
        """Return contamination for this building type, falling back to the global default."""
        return self.building_type_contamination_overrides.get(building_type, self.contamination)
