"""ENG-3d-3 — Windowed Autoencoder training pipeline (PyTorch).

Implements a real, trainable windowed Autoencoder for per-tenant/per-building
anomaly detection.  The Autoencoder catches pattern-level/shape anomalies
that Isolation Forest misses — this is the explicit "blind-spots don't overlap"
guarantee from TRD §3.4.

Architecture
------------
The model is a simple MLP encoder-decoder operating on flattened windows:

    Input:  window_length × n_features  (flattened)
    Encoder: Linear → ReLU → Linear → ReLU → Linear(latent_dim)
    Decoder: Linear → ReLU → Linear → ReLU → Linear(input_dim)
    Output: reconstructed input (same shape as input)
    Loss:   Mean Squared Error (reconstruction error)

Anomaly detection at inference time: windows whose reconstruction error
exceeds a threshold (set at training time as the P-th percentile of
training-set errors) are flagged as anomalous.

EMPIRICAL VALIDATION REQUIRED
------------------------------
- window_length_hours (default 24): validate against COMBED anomaly duration
  characteristics before production deployment.
- autoencoder_latent_dim (default 8): tune against the COMBED golden fixture.
- autoencoder_reconstruction_threshold_percentile (default 95.0): calibrate
  against real pilot data (GTM-2a).

Architecture constraints
------------------------
- One model per tenant, per building.  Never pooled across tenants.
- Training invoked only through Temporal activities, never from apps/api.
- Model and scaler logged to MLflow together so they travel as a unit.
- If COMBED / ECO / public datasets become available, they can be plugged in
  as feature inputs without changing this module's API or the FeatureSetV1 contract.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any
from uuid import UUID

import mlflow
import numpy as np

from models.feature_store.feature_set_v1 import FeatureSetV1
from services.ml_ensemble.config import MLEnsembleConfig
from services.ml_ensemble.feature_assembly import (
    assemble_feature_vector_matrix,
    collect_rule_ids,
)
from services.ml_ensemble.models import TrainingArtifact, TrainingRunResult
from services.ml_ensemble.scaler import BuildingScaler

try:
    import torch
    import torch.nn as nn

    _TORCH_AVAILABLE = True
except ImportError:
    _TORCH_AVAILABLE = False
    torch = None  # type: ignore[assignment]
    nn = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_ARTIFACT_MODEL_DIR = "autoencoder"
_ARTIFACT_SCALER_DIR = "scaler"
_THRESHOLD_KEY = "reconstruction_threshold"


class WindowAutoencoder:
    """MLP encoder-decoder autoencoder for windowed building energy features.

    This class wraps the PyTorch nn.Module so that pickling / MLflow logging
    does not require the caller to import torch directly.

    The underlying nn.Module is accessible via .module for callers that need
    low-level access (e.g., the serving service).

    Parameters
    ----------
    input_dim:
        window_length × n_features (flattened window size).
    hidden_dims:
        List of hidden layer widths for the encoder.  Decoder mirrors these.
    latent_dim:
        Bottleneck width.
    reconstruction_threshold:
        MSE threshold above which a window is flagged anomalous.
        Set by AutoencoderTrainer after fitting on training data.
    """

    def __init__(
        self,
        input_dim: int,
        hidden_dims: list[int],
        latent_dim: int,
        reconstruction_threshold: float = float("inf"),
    ) -> None:
        if not _TORCH_AVAILABLE:
            raise ImportError(
                "PyTorch is required for the Windowed Autoencoder.  "
                "Install it with: pip install 'carbonsense[ml]'"
            )
        self.input_dim = input_dim
        self.hidden_dims = list(hidden_dims)
        self.latent_dim = latent_dim
        self.reconstruction_threshold = reconstruction_threshold
        self.module = self._build_module()

    def _build_module(self) -> Any:
        import torch.nn as _nn  # local import so module is importable without torch

        dims = self.hidden_dims

        encoder_layers: list[Any] = []
        prev = self.input_dim
        for h in dims:
            encoder_layers += [_nn.Linear(prev, h), _nn.ReLU()]
            prev = h
        encoder_layers.append(_nn.Linear(prev, self.latent_dim))

        decoder_layers: list[Any] = []
        prev = self.latent_dim
        for h in reversed(dims):
            decoder_layers += [_nn.Linear(prev, h), _nn.ReLU()]
            prev = h
        decoder_layers.append(_nn.Linear(prev, self.input_dim))

        class _Module(_nn.Module):
            def __init__(self, enc: list[Any], dec: list[Any]) -> None:
                super().__init__()
                self.encoder = _nn.Sequential(*enc)
                self.decoder = _nn.Sequential(*dec)

            def forward(self, x: Any) -> Any:
                return self.decoder(self.encoder(x))

        return _Module(encoder_layers, decoder_layers)

    def reconstruct(self, windows: np.ndarray) -> np.ndarray:
        """Reconstruct windows and return per-window MSE reconstruction errors.

        Parameters
        ----------
        windows:
            Shape (n_windows, input_dim).  Must be scaled with the BuildingScaler
            before calling this method.

        Returns
        -------
        np.ndarray
            Shape (n_windows,).  Each value is the MSE between the input
            and its reconstruction.
        """
        import torch as _torch

        self.module.eval()
        with _torch.no_grad():
            x = _torch.tensor(windows, dtype=_torch.float32)
            reconstructed = self.module(x)
            errors = _torch.mean((x - reconstructed) ** 2, dim=1).numpy()
        return errors  # type: ignore[return-value]

    def is_anomalous(self, reconstruction_errors: np.ndarray) -> np.ndarray:
        """Return a boolean mask: True where error > reconstruction_threshold."""
        return reconstruction_errors > self.reconstruction_threshold


def _build_windows(
    scaled_matrix: np.ndarray,
    window_length: int,
) -> np.ndarray:
    """Slide a window over a scaled feature matrix and return flattened windows.

    Parameters
    ----------
    scaled_matrix:
        Shape (n_timesteps, n_features).  Must already be scaled.
    window_length:
        Number of consecutive timesteps per window.

    Returns
    -------
    np.ndarray
        Shape (n_windows, window_length × n_features).
        n_windows = max(0, n_timesteps - window_length + 1).
    """
    n, f = scaled_matrix.shape
    if n < window_length:
        return np.empty((0, window_length * f), dtype=float)

    windows = []
    for i in range(n - window_length + 1):
        windows.append(scaled_matrix[i : i + window_length].flatten())
    return np.array(windows, dtype=float)


class AutoencoderTrainer:
    """Per-tenant/per-building Autoencoder training pipeline.

    Trains a WindowAutoencoder on normal-operation feature data, computes
    a reconstruction-error threshold from the training set, and logs both
    the model and the BuildingScaler to MLflow.

    Usage
    -----
    ::

        trainer = AutoencoderTrainer()
        result = trainer.train(
            tenant_id=UUID("..."),
            building_id=UUID("..."),
            features=feature_list,
            config=MLEnsembleConfig(),
            mlflow_tracking_uri="file:///tmp/mlruns",
            training_trigger="calendar",
        )
    """

    def train(
        self,
        tenant_id: UUID,
        building_id: UUID,
        features: list[FeatureSetV1],
        config: MLEnsembleConfig | None = None,
        mlflow_tracking_uri: str = "",
        training_trigger: str = "calendar",
        run_tags: dict[str, str] | None = None,
    ) -> TrainingRunResult:
        """Train a Windowed Autoencoder for a single (tenant, building) pair.

        Parameters
        ----------
        tenant_id, building_id:
            Scoping identifiers.  Tenant isolation is enforced upstream by the
            RLS-enforced feature query; this method does not re-verify it.
        features:
            FeatureSetV1 rows for this building's training window.
            Requires at least window_length_hours + 1 usable rows.
        config:
            MLEnsembleConfig.  Defaults to standard configuration.
        mlflow_tracking_uri:
            Local filesystem or remote MLflow tracking URI.
        training_trigger:
            'calendar' | 'drift' | 'feedback_volume'

        Returns
        -------
        TrainingRunResult
            References to the logged model and scaler artifacts.
        """
        if not _TORCH_AVAILABLE:
            raise ImportError(
                "PyTorch is required for AutoencoderTrainer.  "
                "Install with: pip install 'carbonsense[ml]'"
            )
        import torch as _torch

        cfg = config or MLEnsembleConfig()
        _torch.manual_seed(cfg.ae_random_state)

        usable = [f for f in features if not f.low_data_quality]
        min_required = cfg.window_length_hours + 1
        if len(usable) < min_required:
            raise ValueError(
                f"AutoencoderTrainer requires at least {min_required} usable "
                f"feature rows (window_length_hours + 1); got {len(usable)} "
                f"for tenant={tenant_id} building={building_id}."
            )

        rule_ids = collect_rule_ids(usable)
        raw_matrix = np.array(assemble_feature_vector_matrix(usable, rule_ids), dtype=float)

        scaler = BuildingScaler(tenant_id=tenant_id, building_id=building_id, rule_ids=rule_ids)
        scaled_matrix = scaler.fit_transform(raw_matrix)

        windows = _build_windows(scaled_matrix, cfg.window_length_hours)
        if len(windows) == 0:
            raise ValueError(
                f"No windows could be built from {len(usable)} rows "
                f"with window_length_hours={cfg.window_length_hours}."
            )

        input_dim = windows.shape[1]
        ae = WindowAutoencoder(
            input_dim=input_dim,
            hidden_dims=list(cfg.autoencoder_hidden_dims),
            latent_dim=cfg.autoencoder_latent_dim,
        )

        train_losses = self._train_loop(ae, windows, cfg)

        train_errors = ae.reconstruct(windows)
        pct = cfg.autoencoder_reconstruction_threshold_percentile
        threshold = float(np.percentile(train_errors, pct))
        ae.reconstruction_threshold = threshold

        mean_train_error = float(np.mean(train_errors))
        anomaly_rate = float(np.mean(ae.is_anomalous(train_errors)))

        if mlflow_tracking_uri:
            mlflow.set_tracking_uri(mlflow_tracking_uri)

        mlflow.set_experiment(cfg.mlflow_experiment_name)
        tags = {
            "tenant_id": str(tenant_id),
            "building_id": str(building_id),
            "model_type": "autoencoder",
            "trigger": training_trigger,
        }
        if run_tags:
            tags.update(run_tags)

        with mlflow.start_run(tags=tags) as run:
            mlflow.log_params(
                {
                    "window_length_hours": cfg.window_length_hours,
                    "hidden_dims": str(cfg.autoencoder_hidden_dims),
                    "latent_dim": cfg.autoencoder_latent_dim,
                    "epochs": cfg.autoencoder_epochs,
                    "batch_size": cfg.autoencoder_batch_size,
                    "learning_rate": cfg.autoencoder_learning_rate,
                    "threshold_percentile": cfg.autoencoder_reconstruction_threshold_percentile,
                    "n_training_samples": len(usable),
                    "n_windows": len(windows),
                    "input_dim": input_dim,
                    "n_rule_ids": len(rule_ids),
                }
            )
            mlflow.log_metrics(
                {
                    "final_train_loss": float(train_losses[-1]) if train_losses else 0.0,
                    "reconstruction_threshold": threshold,
                    "mean_train_reconstruction_error": mean_train_error,
                    "train_anomaly_rate": anomaly_rate,
                    "n_features": float(raw_matrix.shape[1]),
                }
            )
            mlflow.log_dict({"rule_ids": rule_ids}, "rule_ids.json")
            mlflow.log_dict(
                {_THRESHOLD_KEY: threshold, "input_dim": input_dim},
                "model_config.json",
            )

            with tempfile.TemporaryDirectory() as tmp_dir:
                model_path = Path(tmp_dir) / "autoencoder.pt"
                _torch.save(
                    {
                        "state_dict": ae.module.state_dict(),
                        "input_dim": ae.input_dim,
                        "hidden_dims": ae.hidden_dims,
                        "latent_dim": ae.latent_dim,
                        "reconstruction_threshold": ae.reconstruction_threshold,
                    },
                    model_path,
                )
                mlflow.log_artifact(str(model_path), _ARTIFACT_MODEL_DIR)
                scaler_path = scaler.save(Path(tmp_dir))
                mlflow.log_artifact(str(scaler_path), _ARTIFACT_SCALER_DIR)

            run_id = run.info.run_id
            model_uri = mlflow.get_artifact_uri(_ARTIFACT_MODEL_DIR)
            scaler_uri = mlflow.get_artifact_uri(_ARTIFACT_SCALER_DIR)

            registered_version: str | None = None
            try:
                from models.registry.register import register_model_version

                registered_version = register_model_version(
                    run_id=run_id,
                    artifact_path=_ARTIFACT_MODEL_DIR,
                    tenant_id=tenant_id,
                    building_id=building_id,
                    model_type="autoencoder",
                    artifact_uri=model_uri,
                )
            except Exception:
                # See IsolationForestTrainer's identical try/except for why
                # a registry-side failure must not fail training itself.
                logger.exception(
                    "Autoencoder training succeeded but Model Registry "
                    "registration failed for tenant=%s building=%s run_id=%s",
                    tenant_id,
                    building_id,
                    run_id,
                )

        logger.info(
            "Autoencoder trained: tenant=%s building=%s samples=%d windows=%d "
            "threshold=%.4f anomaly_rate=%.3f run_id=%s",
            tenant_id,
            building_id,
            len(usable),
            len(windows),
            threshold,
            anomaly_rate,
            run_id,
        )

        return TrainingRunResult(
            tenant_id=tenant_id,
            building_id=building_id,
            model_type="autoencoder",
            training_trigger=training_trigger,
            mlflow_run_id=run_id,
            model_artifact=TrainingArtifact(
                run_id=run_id,
                artifact_path=_ARTIFACT_MODEL_DIR,
                artifact_uri=model_uri,
            ),
            scaler_artifact=TrainingArtifact(
                run_id=run_id,
                artifact_path=_ARTIFACT_SCALER_DIR,
                artifact_uri=scaler_uri,
            ),
            rule_ids_used=rule_ids,
            n_training_samples=len(usable),
            metrics={
                "reconstruction_threshold": threshold,
                "mean_train_reconstruction_error": mean_train_error,
                "train_anomaly_rate": anomaly_rate,
                "n_features": float(raw_matrix.shape[1]),
                "n_windows": float(len(windows)),
            },
            registered_version=registered_version,
        )

    @staticmethod
    def _train_loop(
        ae: WindowAutoencoder,
        windows: np.ndarray,
        cfg: MLEnsembleConfig,
    ) -> list[float]:
        """Run the training loop and return per-epoch losses."""
        import torch as _torch
        import torch.nn as _nn
        from torch.utils.data import DataLoader as _DataLoader
        from torch.utils.data import TensorDataset as _TensorDataset

        tensor = _torch.tensor(windows, dtype=_torch.float32)
        dataset = _TensorDataset(tensor)
        loader = _DataLoader(dataset, batch_size=cfg.autoencoder_batch_size, shuffle=True)

        optimizer = _torch.optim.Adam(ae.module.parameters(), lr=cfg.autoencoder_learning_rate)
        loss_fn = _nn.MSELoss()

        ae.module.train()
        losses: list[float] = []
        for _ in range(cfg.autoencoder_epochs):
            epoch_loss = 0.0
            for (batch,) in loader:
                optimizer.zero_grad()
                reconstruction = ae.module(batch)
                loss = loss_fn(reconstruction, batch)
                loss.backward()
                optimizer.step()
                epoch_loss += loss.item() * len(batch)
            losses.append(epoch_loss / len(windows))

        ae.module.eval()
        return losses


def load_autoencoder_from_mlflow(run_id: str, artifact_path: str) -> WindowAutoencoder:
    """Load a WindowAutoencoder from a logged MLflow artifact.

    Parameters
    ----------
    run_id:
        MLflow run ID.
    artifact_path:
        Artifact sub-path where the model's .pt file was logged.

    Returns
    -------
    WindowAutoencoder
        Restored model with the original architecture and threshold.
    """
    import torch as _torch

    # Use run_id + artifact_path directly — mlflow.get_artifact_uri() requires an
    # active run context and raises MlflowException when called outside one.
    local_dir = mlflow.artifacts.download_artifacts(run_id=run_id, artifact_path=artifact_path)
    pt_files = list(Path(local_dir).glob("*.pt"))
    if not pt_files:
        raise FileNotFoundError(
            f"No .pt file found in artifact directory {local_dir!r} "
            f"for run_id={run_id!r} artifact_path={artifact_path!r}."
        )
    # weights_only=False is required to deserialise non-tensor fields (hidden_dims list,
    # threshold float, etc.). Safe here because the checkpoint is a project-internal
    # artifact written by AutoencoderTrainer and loaded only from the project's own
    # MLflow instance — never from an untrusted source.
    checkpoint = _torch.load(pt_files[0], weights_only=False)  # noqa: S614

    ae = WindowAutoencoder(
        input_dim=checkpoint["input_dim"],
        hidden_dims=checkpoint["hidden_dims"],
        latent_dim=checkpoint["latent_dim"],
        reconstruction_threshold=checkpoint["reconstruction_threshold"],
    )
    ae.module.load_state_dict(checkpoint["state_dict"])
    ae.module.eval()
    return ae
