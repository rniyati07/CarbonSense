"""ENG-3g-1 — SHAP computation against the ML Ensemble's feature inputs.

Computes SHAP values for a given feature_set_v1 row against the trained ML Ensemble
(IsolationForest and/or Windowed Autoencoder) and returns a ranked list of TopFeature
objects with plain-language descriptions from the feature registry.

TRD v2.0 §3.7 requirement: SHAP values computed against the ML Ensemble's feature
inputs are combined with rule citations and STL context by the BundleAssembler.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

import numpy as np
import shap

from services.explainability.feature_registry import render
from services.explainability.models import TopFeature

logger = logging.getLogger(__name__)


class PredictCallable(Protocol):
    """Protocol for a model predict function (for KernelExplainer on Autoencoders)."""

    def __call__(self, x: np.ndarray) -> np.ndarray: ...


class SHAPExplainer:
    """Computes SHAP feature attributions against the ML Ensemble.

    For IsolationForest (tree-based): uses ``shap.TreeExplainer`` — exact, fast.
    For Autoencoder or other black-box models: uses ``shap.KernelExplainer`` with a
    provided predict callable and background dataset.

    Usage::

        explainer = SHAPExplainer(
            tree_model=iso_forest,
            feature_names=feature_names,
            top_n=5,
        )
        top_features = explainer.explain(feature_row)
    """

    def __init__(
        self,
        *,
        tree_model: Any | None = None,
        kernel_predict_fn: PredictCallable | None = None,
        kernel_background: np.ndarray | None = None,
        feature_names: list[str],
        top_n: int = 5,
    ) -> None:
        """Initialise a SHAP explainer.

        Args:
            tree_model:          A fitted sklearn tree-based estimator (IsolationForest).
                                 When provided, TreeExplainer is used.
            kernel_predict_fn:   A callable ``f(X) -> scores`` for black-box models
                                 (Autoencoder). Required when *tree_model* is None.
            kernel_background:   Background dataset for KernelExplainer (required when
                                 using *kernel_predict_fn*). Shape: (n_samples, n_features).
            feature_names:       Ordered list of feature_set_v1 feature names matching
                                 the column order of the input arrays.
            top_n:               Number of top features to return (ranked by |shap_value|).
        """
        if tree_model is None and kernel_predict_fn is None:
            raise ValueError("Either tree_model or kernel_predict_fn must be provided.")
        self._feature_names = feature_names
        self._top_n = top_n

        explainer: shap.TreeExplainer | shap.KernelExplainer  # type: ignore[type-arg]
        if tree_model is not None:
            explainer = shap.TreeExplainer(tree_model)
            self._mode = "tree"
        else:
            if kernel_background is None:
                raise ValueError("kernel_background must be provided when using kernel_predict_fn")
            explainer = shap.KernelExplainer(
                kernel_predict_fn,
                kernel_background,  # type: ignore[arg-type]
            )
            self._mode = "kernel"
        self._explainer = explainer

    def explain(self, feature_row: dict[str, float] | np.ndarray) -> list[TopFeature]:
        """Compute SHAP values for a single feature row and return ranked TopFeatures.

        Args:
            feature_row: Either a dict mapping feature names to values, or a 1-D
                         numpy array in the same order as *feature_names*.

        Returns:
            List of TopFeature sorted descending by abs(shap_value), limited to top_n.
        """
        x = self._to_array(feature_row)
        shap_values = self._compute_shap_values(x)

        # Build ranked list
        pairs: list[tuple[str, float]] = list(zip(self._feature_names, shap_values, strict=False))
        pairs.sort(key=lambda t: abs(t[1]), reverse=True)
        top = pairs[: self._top_n]

        return [
            TopFeature(
                feature=name,
                shap_value=round(sv, 4),
                plain_language=render(name, sv),
            )
            for name, sv in top
        ]

    def _to_array(self, feature_row: dict[str, float] | np.ndarray) -> np.ndarray:
        """Convert dict or array to a 2-D numpy array for the SHAP explainer."""
        if isinstance(feature_row, dict):
            arr = np.array(
                [feature_row.get(name, 0.0) for name in self._feature_names],
                dtype=float,
            )
        else:
            arr = np.asarray(feature_row, dtype=float).flatten()

        if arr.shape[0] != len(self._feature_names):
            raise ValueError(
                f"feature_row has {arr.shape[0]} values but "
                f"{len(self._feature_names)} feature names were registered."
            )
        return arr.reshape(1, -1)

    def _compute_shap_values(self, x_2d: np.ndarray) -> np.ndarray:
        """Return a 1-D array of SHAP values for the single row *x_2d*."""
        raw = self._explainer.shap_values(x_2d)

        # TreeExplainer on IsolationForest returns shape (1, n_features) or
        # (n_features,) depending on shap version.
        arr = np.asarray(raw)
        if arr.ndim == 2:
            arr = arr[0]
        elif arr.ndim == 1 and arr.shape[0] == 1:
            # Some versions return (1,) for single-output models — shouldn't hit
            # this for IsolationForest but guard it anyway
            arr = arr[0]

        # KernelExplainer may return a list-of-arrays for multi-output; take index 0
        if isinstance(raw, list):
            arr = np.asarray(raw[0]).flatten()

        return arr.flatten()
