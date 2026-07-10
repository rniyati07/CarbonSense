"""Unit tests for services/explainability/feature_registry.py.

Verifies that the feature registry is:
- Deterministic (same inputs → same output)
- Complete (all registered features produce non-empty plain_language)
- Safe for unknown features (never raises, always returns a string)
"""

from __future__ import annotations

import pytest

import services.explainability.feature_registry as registry


@pytest.mark.unit
class TestFeatureRegistry:
    def test_all_registered_features_produce_non_empty_strings(self) -> None:
        """Every entry in the registry must produce plain_language."""
        for feature in registry.list_registered_features():
            result = registry.render(feature, shap_value=0.35)
            assert isinstance(result, str), f"Expected str for {feature}"
            assert len(result) > 0, f"Empty string for feature {feature}"

    def test_render_positive_shap_uses_above(self) -> None:
        result = registry.render("after_hours_kwh_ratio", shap_value=0.41)
        assert "above" in result.lower()

    def test_render_negative_shap_uses_below(self) -> None:
        result = registry.render("after_hours_kwh_ratio", shap_value=-0.20)
        assert "below" in result.lower()

    def test_render_known_feature_contains_percentage(self) -> None:
        result = registry.render("after_hours_kwh_ratio", shap_value=0.41)
        # 0.41 → pct=41
        assert "41" in result

    def test_render_stl_residual(self) -> None:
        result = registry.render("stl_residual_z", shap_value=0.30)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_render_unknown_feature_does_not_raise(self) -> None:
        result = registry.render("some_unknown_feature_xyz", shap_value=0.50)
        assert isinstance(result, str)
        assert "some_unknown_feature_xyz" in result

    def test_render_is_deterministic(self) -> None:
        result1 = registry.render("rolling_24h_kwh_mean", shap_value=0.25)
        result2 = registry.render("rolling_24h_kwh_mean", shap_value=0.25)
        assert result1 == result2

    def test_is_registered_known(self) -> None:
        assert registry.is_registered("after_hours_kwh_ratio") is True

    def test_is_registered_unknown(self) -> None:
        assert registry.is_registered("nonexistent_feature_abc") is False

    def test_list_registered_features_is_sorted(self) -> None:
        features = registry.list_registered_features()
        assert features == sorted(features)

    def test_list_registered_features_not_empty(self) -> None:
        assert len(registry.list_registered_features()) >= 5

    def test_registry_version_is_set(self) -> None:
        assert registry.REGISTRY_VERSION.startswith("feature_registry_v")

    def test_zero_shap_value_safe(self) -> None:
        """Edge case: shap_value=0.0 should not produce divide-by-zero errors."""
        result = registry.render("after_hours_kwh_ratio", shap_value=0.0)
        assert isinstance(result, str)
        assert "0" in result
