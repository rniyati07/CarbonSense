"""ENG-3d — ML Ensemble interfaces (Protocols).

Protocol definitions for injectable collaborators used by the training
pipelines and serving service.  Using Protocol (structural typing) keeps
the service decoupled from specific storage implementations — tests inject
InMemoryModelRegistry while production injects MLflowModelRegistry.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable
from uuid import UUID

if TYPE_CHECKING:
    from sklearn.ensemble import IsolationForest
    from sklearn.preprocessing import StandardScaler

    from models.training.autoencoder import WindowAutoencoder
    from services.ml_ensemble.models import TrainingRunResult


@runtime_checkable
class ModelRegistryProtocol(Protocol):
    """Abstract interface for loading and saving ML ensemble model artifacts.

    The production implementation (MLflowModelRegistry in models/serving/)
    uses MLflow's tracking API.  Tests inject InMemoryModelRegistry.

    TODO(ENG-6a): Implement MLflowModelRegistry in models/serving/ once ENG-6a has
    stood up the Model Registry with the models:/{tenant_id}/{building_id}/ml_ensemble/{version}
    URI convention (TRD §6.1). MLflowModelRegistry.load_isolation_forest() and
    load_autoencoder() should load the "currently-promoted" registered model version
    for the given (tenant, building) pair. Promotion gating belongs to ENG-6c.
    ENG-3d-4 depends on ENG-6a per the ROADMAP dependency list.
    """

    def save_training_result(self, result: TrainingRunResult) -> None:
        """Persist a TrainingRunResult for later retrieval by the serving service.

        Parameters
        ----------
        result:
            The TrainingRunResult produced by a training pipeline.
        """
        ...

    def load_isolation_forest(
        self,
        tenant_id: UUID,
        building_id: UUID,
    ) -> tuple[IsolationForest, StandardScaler, list[str]]:
        """Load the currently-promoted Isolation Forest model for a building.

        Returns
        -------
        (model, scaler, rule_ids)
            model   — trained IsolationForest instance
            scaler  — fitted StandardScaler; apply before calling model.predict()
            rule_ids — ordered list of rule_ids the scaler was fit on
        """
        ...

    def load_autoencoder(
        self,
        tenant_id: UUID,
        building_id: UUID,
    ) -> tuple[WindowAutoencoder, StandardScaler, list[str]]:
        """Load the currently-promoted Autoencoder model for a building.

        Returns
        -------
        (model, scaler, rule_ids)
            model   — trained WindowAutoencoder instance (eval mode)
            scaler  — fitted StandardScaler; apply before calling model.reconstruct()
            rule_ids — ordered list of rule_ids the scaler was fit on
        """
        ...
