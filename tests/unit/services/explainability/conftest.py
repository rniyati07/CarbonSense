"""Shared fixtures for explainability unit tests."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import numpy as np
import pytest
from sklearn.ensemble import IsolationForest

from services.explainability.models import (
    ConfidenceBand,
    EvidenceWindow,
    RuleCitation,
    TopFeature,
)

# Stable IDs for reproducible tests
TENANT_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
BUILDING_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
FINDING_ID = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")

FEATURE_NAMES = [
    "after_hours_kwh_ratio",
    "weekend_floor_load",
    "stl_residual_z",
    "rolling_24h_kwh_mean",
    "peak_hour_ratio",
]

EVIDENCE_START = datetime(2026, 6, 1, 22, 0, 0, tzinfo=timezone.utc)
EVIDENCE_END = datetime(2026, 6, 2, 5, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def evidence_window() -> EvidenceWindow:
    return EvidenceWindow(start=EVIDENCE_START, end=EVIDENCE_END)


@pytest.fixture()
def confidence_band_high() -> ConfidenceBand:
    return ConfidenceBand(lower=0.62, upper=0.81)


@pytest.fixture()
def confidence_band_wide() -> ConfidenceBand:
    """Wide band simulates a low-confidence (cold-start / ML-only) finding."""
    return ConfidenceBand(lower=0.30, upper=0.72)


@pytest.fixture()
def rule_citations_hvac() -> list[RuleCitation]:
    return [
        RuleCitation(
            rule_id="hvac_after_hours_v3",
            version=3,
            citation="ASHRAE Guideline 36 — HVAC scheduling FDD pattern",
        )
    ]


@pytest.fixture()
def top_features_sample() -> list[TopFeature]:
    return [
        TopFeature(
            feature="after_hours_kwh_ratio",
            shap_value=0.41,
            plain_language=(
                "Energy use after declared business hours was 41% above"
                " the building's normal pattern"
            ),
        ),
        TopFeature(
            feature="weekend_floor_load",
            shap_value=0.19,
            plain_language="Weekend baseline consumption was 19% above expected levels,"
            " suggesting equipment did not power down as scheduled",
        ),
    ]


@pytest.fixture()
def trained_iso_forest() -> IsolationForest:
    """A minimal trained IsolationForest on synthetic data."""
    rng = np.random.default_rng(42)
    X = rng.standard_normal((200, len(FEATURE_NAMES)))
    clf = IsolationForest(n_estimators=10, random_state=42, contamination=0.05)
    clf.fit(X)
    return clf


@pytest.fixture()
def normal_feature_row() -> dict[str, float]:
    return {
        "after_hours_kwh_ratio": 0.05,
        "weekend_floor_load": 0.02,
        "stl_residual_z": 0.5,
        "rolling_24h_kwh_mean": 100.0,
        "peak_hour_ratio": 1.1,
    }


@pytest.fixture()
def anomalous_feature_row() -> dict[str, float]:
    return {
        "after_hours_kwh_ratio": 1.8,   # very high after-hours usage
        "weekend_floor_load": 0.95,     # high weekend load
        "stl_residual_z": 4.2,          # large STL residual
        "rolling_24h_kwh_mean": 320.0,  # above baseline
        "peak_hour_ratio": 2.3,         # extreme peak ratio
    }
