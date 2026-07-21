"""ENG-3d — Temporal activity unit tests.

Tests that:
- train_isolation_forest_activity returns MLTrainingResult with status='skipped'
  when the feature store stub returns no data (which is the current state).
- train_autoencoder_activity behaves identically.
- Both DTOs can be serialised / deserialised (Temporal round-trip compatibility).

Full end-to-end activity tests (with real features) are in the integration suite.
"""

from __future__ import annotations

import asyncio

import pytest

from orchestration.temporal.dto import MLTrainingInput, MLTrainingResult


class TestMLTrainingInputDTO:
    def test_is_frozen_dataclass(self) -> None:
        inp = MLTrainingInput(
            tenant_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            building_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        )
        with pytest.raises((AttributeError, TypeError)):
            inp.tenant_id = "other"  # type: ignore[misc]

    def test_trigger_default(self) -> None:
        inp = MLTrainingInput(
            tenant_id="t1",
            building_id="b1",
        )
        assert inp.trigger == "calendar"

    def test_building_type_default(self) -> None:
        inp = MLTrainingInput(tenant_id="t1", building_id="b1")
        assert inp.building_type == "unknown"


class TestMLTrainingResultDTO:
    def test_is_frozen_dataclass(self) -> None:
        r = MLTrainingResult(
            tenant_id="t1",
            building_id="b1",
            model_type="isolation_forest",
            mlflow_run_id="run-1",
            model_artifact_uri="file:///tmp/m",
            scaler_artifact_uri="file:///tmp/s",
            n_training_samples=100,
            status="completed",
        )
        with pytest.raises((AttributeError, TypeError)):
            r.status = "failed"  # type: ignore[misc]

    def test_status_default_completed(self) -> None:
        r = MLTrainingResult(
            tenant_id="t1",
            building_id="b1",
            model_type="isolation_forest",
            mlflow_run_id="run-1",
            model_artifact_uri="",
            scaler_artifact_uri="",
            n_training_samples=0,
        )
        assert r.status == "completed"


class TestTrainActivitiesStubBehaviour:
    """Activities must gracefully skip when the feature store returns no data.

    ENG-6: _fetch_training_features now queries the real feature store
    (models/feature_store/repository.py) instead of being a hardcoded
    stub -- these tests patch it directly to exercise the "no data"
    path without needing a live database, matching this test file's own
    original intent (see the module docstring). Real feature-store-backed
    behavior is covered by tests/unit/models/feature_store/test_repository.py
    and tests/unit/pipelines/training/test_train_and_evaluate.py.
    """

    def test_train_if_activity_returns_skipped_when_no_features(self) -> None:
        from orchestration.temporal.activities.ml_ensemble_activities import (
            train_isolation_forest_activity,
        )

        inp = MLTrainingInput(
            tenant_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            building_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            trigger="calendar",
        )

        # Run outside of a Temporal worker — the activity function is an async def.
        # We patch the heartbeat context and the feature-store fetch to no-ops.
        import unittest.mock as mock

        with (
            mock.patch("temporalio.activity.heartbeat"),
            mock.patch(
                "orchestration.temporal.activities.ml_ensemble_activities._fetch_training_features",
                new=mock.AsyncMock(return_value=[]),
            ),
        ):
            result = asyncio.run(train_isolation_forest_activity(inp))

        assert result.status == "skipped"
        assert result.model_type == "isolation_forest"
        assert result.tenant_id == inp.tenant_id
        assert result.building_id == inp.building_id

    def test_train_ae_activity_returns_skipped_when_no_features(self) -> None:
        from orchestration.temporal.activities.ml_ensemble_activities import (
            train_autoencoder_activity,
        )

        inp = MLTrainingInput(
            tenant_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            building_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            trigger="drift",
        )

        import unittest.mock as mock

        with (
            mock.patch("temporalio.activity.heartbeat"),
            mock.patch(
                "orchestration.temporal.activities.ml_ensemble_activities._fetch_training_features",
                new=mock.AsyncMock(return_value=[]),
            ),
        ):
            result = asyncio.run(train_autoencoder_activity(inp))

        assert result.status == "skipped"
        assert result.model_type == "autoencoder"
