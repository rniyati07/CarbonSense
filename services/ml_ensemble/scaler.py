"""ENG-3d — Per-building feature scaler.

Wraps sklearn.preprocessing.StandardScaler with:
  - Explicit per-building ownership (each building has its own scaler)
  - Pickle-based serialisation for persistence alongside the model in MLflow
  - rule_ids stored so the feature ordering can be reconstructed at inference

DATA_AND_MODEL_STRATEGY §4.1 (PROPOSED):
    Scaling is NOT global.  Each building owns its own scaler.
    The scaler must travel with the model in the registry (ENG-3d-1 spec).
    Fit and persist the scaler alongside each building's model version so
    it is loaded together with the model at serving time.
"""

from __future__ import annotations

import pickle
from pathlib import Path
from uuid import UUID

import numpy as np
from sklearn.preprocessing import StandardScaler


class BuildingScaler:
    """Per-building StandardScaler with serialisation and rule_ids tracking.

    Attributes
    ----------
    tenant_id, building_id:
        Ownership identifiers.  A scaler MUST NOT be shared across tenants
        or across buildings — each (tenant, building) pair has its own instance.
    rule_ids:
        Ordered list of rule_ids whose binary indicators were included in the
        feature vector at fit time.  Serving must use the same list in the
        same order to produce a compatible feature vector.
    """

    SCALER_FILE = "scaler.pkl"

    def __init__(self, tenant_id: UUID, building_id: UUID, rule_ids: list[str]) -> None:
        self.tenant_id = tenant_id
        self.building_id = building_id
        self.rule_ids = list(rule_ids)
        self._scaler = StandardScaler()
        self._is_fitted = False

    # ------------------------------------------------------------------ #
    # Fit / transform
    # ------------------------------------------------------------------ #

    def fit(self, feature_matrix: np.ndarray) -> BuildingScaler:
        """Fit the scaler on the training feature matrix.

        Parameters
        ----------
        feature_matrix:
            Shape (n_samples, n_features).  Each row is a numeric feature
            vector produced by FeatureSetV1.to_numeric_vector(self.rule_ids).
        """
        self._scaler.fit(feature_matrix)
        self._is_fitted = True
        return self

    def transform(self, feature_matrix: np.ndarray) -> np.ndarray:
        """Apply the fitted scaler to a feature matrix.

        Parameters
        ----------
        feature_matrix:
            Shape (n_samples, n_features).

        Returns
        -------
        np.ndarray
            Scaled feature matrix with zero mean and unit variance per feature.
        """
        if not self._is_fitted:
            raise RuntimeError(
                "BuildingScaler.transform() called before fit().  "
                "Call fit(training_matrix) first."
            )
        return self._scaler.transform(feature_matrix)  # type: ignore[no-any-return]

    def fit_transform(self, feature_matrix: np.ndarray) -> np.ndarray:
        """Fit the scaler and transform in one step (for training pipelines)."""
        return self.fit(feature_matrix).transform(feature_matrix)

    @property
    def is_fitted(self) -> bool:
        return self._is_fitted

    # ------------------------------------------------------------------ #
    # Serialisation — the scaler is persisted as a pickle file and logged
    # to MLflow alongside the model artifact so they travel together.
    # ------------------------------------------------------------------ #

    def save(self, directory: Path | str) -> Path:
        """Serialise the scaler to a pickle file in the given directory.

        Parameters
        ----------
        directory:
            Directory where the scaler file will be written.
            The file is named ``scaler.pkl`` and can be logged to MLflow
            as an artifact immediately after this call.

        Returns
        -------
        Path
            Full path to the written pickle file.
        """
        target = Path(directory) / self.SCALER_FILE
        with open(target, "wb") as fh:
            pickle.dump(
                {
                    "tenant_id": str(self.tenant_id),
                    "building_id": str(self.building_id),
                    "rule_ids": self.rule_ids,
                    "sklearn_scaler": self._scaler,
                    "is_fitted": self._is_fitted,
                },
                fh,
            )
        return target

    @classmethod
    def load(cls, path: Path | str) -> BuildingScaler:
        """Deserialise a scaler from a pickle file.

        Parameters
        ----------
        path:
            Path to the pickle file written by BuildingScaler.save().

        Returns
        -------
        BuildingScaler
            Restored instance with the original tenant_id, building_id,
            rule_ids, and fitted sklearn scaler.
        """
        with open(path, "rb") as fh:
            state = pickle.load(fh)  # noqa: S301 — trusted internal artifact

        instance = cls(
            tenant_id=UUID(state["tenant_id"]),
            building_id=UUID(state["building_id"]),
            rule_ids=state["rule_ids"],
        )
        instance._scaler = state["sklearn_scaler"]
        instance._is_fitted = state["is_fitted"]
        return instance
