"""Unit tests for services/explainability/shap_explainer.py.

Tests SHAP computation against a synthetic IsolationForest.
"""

from __future__ import annotations

import numpy as np
import pytest
from sklearn.ensemble import IsolationForest

from services.explainability.shap_explainer import SHAPExplainer
from tests.unit.services.explainability.conftest import FEATURE_NAMES


@pytest.mark.unit
class TestSHAPExplainerTree:
    def test_explain_returns_top_features(
        self,
        trained_iso_forest: IsolationForest,
        anomalous_feature_row: dict[str, float],
    ) -> None:
        explainer = SHAPExplainer(
            tree_model=trained_iso_forest,
            feature_names=FEATURE_NAMES,
            top_n=5,
        )
        top_features = explainer.explain(anomalous_feature_row)
        assert len(top_features) > 0
        assert len(top_features) <= 5

    def test_top_features_sorted_descending_by_abs_shap(
        self,
        trained_iso_forest: IsolationForest,
        anomalous_feature_row: dict[str, float],
    ) -> None:
        explainer = SHAPExplainer(
            tree_model=trained_iso_forest,
            feature_names=FEATURE_NAMES,
            top_n=5,
        )
        top_features = explainer.explain(anomalous_feature_row)
        abs_values = [abs(f.shap_value) for f in top_features]
        assert abs_values == sorted(abs_values, reverse=True), (
            "TopFeatures must be ranked descending by abs(shap_value)"
        )

    def test_top_features_have_plain_language(
        self,
        trained_iso_forest: IsolationForest,
        anomalous_feature_row: dict[str, float],
    ) -> None:
        explainer = SHAPExplainer(
            tree_model=trained_iso_forest,
            feature_names=FEATURE_NAMES,
            top_n=5,
        )
        top_features = explainer.explain(anomalous_feature_row)
        for tf in top_features:
            assert isinstance(tf.plain_language, str)
            assert len(tf.plain_language) > 0

    def test_top_n_limits_output(
        self,
        trained_iso_forest: IsolationForest,
        anomalous_feature_row: dict[str, float],
    ) -> None:
        explainer = SHAPExplainer(
            tree_model=trained_iso_forest,
            feature_names=FEATURE_NAMES,
            top_n=2,
        )
        top_features = explainer.explain(anomalous_feature_row)
        assert len(top_features) <= 2

    def test_explain_with_numpy_array(
        self,
        trained_iso_forest: IsolationForest,
    ) -> None:
        explainer = SHAPExplainer(
            tree_model=trained_iso_forest,
            feature_names=FEATURE_NAMES,
        )
        row = np.array([1.8, 0.95, 4.2, 320.0, 2.3])
        top_features = explainer.explain(row)
        assert len(top_features) > 0

    def test_wrong_feature_count_raises(
        self,
        trained_iso_forest: IsolationForest,
    ) -> None:
        """A numpy array with the wrong number of elements must raise ValueError."""
        explainer = SHAPExplainer(
            tree_model=trained_iso_forest,
            feature_names=FEATURE_NAMES,
        )
        wrong_length_array = np.array([1.0, 2.0])  # 2 values but 5 features registered
        with pytest.raises(ValueError, match="feature names"):
            explainer.explain(wrong_length_array)

    def test_no_model_provided_raises(self) -> None:
        with pytest.raises(ValueError, match="Either tree_model or kernel_predict_fn"):
            SHAPExplainer(feature_names=FEATURE_NAMES)

    def test_kernel_missing_background_raises(self) -> None:
        def dummy_predict(X: np.ndarray) -> np.ndarray:
            return X.sum(axis=1)

        with pytest.raises(ValueError, match="kernel_background"):
            SHAPExplainer(
                kernel_predict_fn=dummy_predict,
                feature_names=FEATURE_NAMES,
            )
