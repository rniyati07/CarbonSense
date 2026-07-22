"""Unit-level coverage of run_batch_feature_engineering()'s orchestration
logic (rule-fire aggregation, STL calendar-error skip, conditional
persistence) via patching the DB/service boundaries -- a real end-to-end
run against a live database is exercised instead by
tests/integration/test_training_pipeline_e2e.py (ENG-6e), matching
test_train_and_evaluate.py's identical rationale.
"""

from __future__ import annotations

import contextlib
import datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from pipelines.feature_engineering.batch_pipeline import run_batch_feature_engineering
from services.explainability.models import ExplainabilityBundle, RuleCitation
from services.ingestion.models import NormalizedReading
from services.rules_engine.models import Finding
from services.stl_detection.exceptions import CalendarLookupError
from services.stl_detection.models import STLResidualResult


@contextlib.asynccontextmanager
async def _noop_tenant_scope(session, tenant_id):  # noqa: ANN001
    yield session


class _FakeSessionCtx:
    async def __aenter__(self):  # noqa: ANN204
        return AsyncMock()

    async def __aexit__(self, *args):  # noqa: ANN204
        return False


def _make_reading(tenant_id, circuit_id, ts) -> NormalizedReading:  # noqa: ANN001
    return NormalizedReading(
        tenant_id=tenant_id,
        circuit_id=circuit_id,
        ts=ts,
        kwh=5.0,
        source_system="db",
        ingestion_timestamp=ts,
        normalization_version="v1",
    )


@pytest.mark.unit
class TestRunBatchFeatureEngineering:
    @pytest.mark.asyncio
    async def test_assembles_and_persists_features_when_persist_true(self) -> None:
        tenant_id, building_id, circuit_id = uuid4(), uuid4(), uuid4()
        ts = datetime.datetime(2026, 1, 5, 10, 0, tzinfo=datetime.UTC)
        reading = _make_reading(tenant_id, circuit_id, ts)
        stl_result = STLResidualResult(
            tenant_id=tenant_id,
            circuit_id=circuit_id,
            ts=ts,
            kwh=5.0,
            day_type="business_day",
            stl_residual=0.4,
            residual_zscore=1.2,
            residual_magnitude=0.4,
            is_anomalous=False,
            low_data_quality=False,
        )
        finding = Finding(
            finding_id=uuid4(),
            tenant_id=tenant_id,
            building_id=building_id,
            circuit_id=circuit_id,
            layer_origin="domain_rule",
            evidence_window_start=ts,
            evidence_window_end=ts,
            confidence=None,
            status="open",
            explainability_bundle=ExplainabilityBundle(
                finding_id=uuid4(),
                contributing_layers=["domain_rule"],
                rule_citations=[
                    RuleCitation(rule_id="hvac_after_hours_v3", version=3, citation="ASHRAE")
                ],
                evidence_window={"start": ts, "end": ts},
            ),
        )

        save_features_mock = AsyncMock()
        with (
            patch(
                "pipelines.feature_engineering.batch_pipeline.get_session_factory",
                return_value=lambda: _FakeSessionCtx(),
            ),
            patch("pipelines.feature_engineering.batch_pipeline.tenant_scope", _noop_tenant_scope),
            patch(
                "services.stl_detection.repository.STLReadingsRepository.get_readings_by_circuit",
                AsyncMock(return_value={circuit_id: [reading]}),
            ),
            patch(
                "services.stl_detection.repository.TimescaleCalendarRepository."
                "fetch_calendar_entries",
                AsyncMock(return_value=[]),
            ),
            patch(
                "services.rules_engine.repository.RulesEngineReadingsRepository.get_readings",
                AsyncMock(return_value=[]),
            ),
            patch(
                "services.rules_engine.repository.RulesEngineReadingsRepository.get_circuit_types",
                AsyncMock(return_value={}),
            ),
            patch(
                "services.rules_engine.repository.RulesEngineReadingsRepository."
                "get_building_context",
                AsyncMock(return_value={}),
            ),
            patch(
                "services.rules_engine.service.DomainRuleEngineService.process_readings",
                lambda self, **kwargs: [finding],
            ),
            patch(
                "services.stl_detection.service.STLDetectionService."
                "analyse_circuit_window_with_repo",
                return_value=[stl_result],
            ),
            patch(
                "pipelines.feature_engineering.batch_pipeline.FeatureStoreRepository"
            ) as mock_repo_cls,
        ):
            mock_repo_cls.return_value.save_features = save_features_mock

            features = await run_batch_feature_engineering(
                tenant_id, building_id, ts, ts + datetime.timedelta(hours=1)
            )

        assert len(features) == 1
        assert features[0].circuit_id == circuit_id
        assert features[0].stl_residual_magnitude == 0.4
        assert features[0].rule_fire_indicators == {"hvac_after_hours_v3": True}
        save_features_mock.assert_awaited_once_with(features)

    @pytest.mark.asyncio
    async def test_does_not_persist_when_persist_false(self) -> None:
        tenant_id, building_id, circuit_id = uuid4(), uuid4(), uuid4()
        ts = datetime.datetime(2026, 1, 5, 10, 0, tzinfo=datetime.UTC)
        reading = _make_reading(tenant_id, circuit_id, ts)

        save_features_mock = AsyncMock()
        with (
            patch(
                "pipelines.feature_engineering.batch_pipeline.get_session_factory",
                return_value=lambda: _FakeSessionCtx(),
            ),
            patch("pipelines.feature_engineering.batch_pipeline.tenant_scope", _noop_tenant_scope),
            patch(
                "services.stl_detection.repository.STLReadingsRepository.get_readings_by_circuit",
                AsyncMock(return_value={circuit_id: [reading]}),
            ),
            patch(
                "services.stl_detection.repository.TimescaleCalendarRepository."
                "fetch_calendar_entries",
                AsyncMock(return_value=[]),
            ),
            patch(
                "services.rules_engine.repository.RulesEngineReadingsRepository.get_readings",
                AsyncMock(return_value=[]),
            ),
            patch(
                "services.rules_engine.repository.RulesEngineReadingsRepository.get_circuit_types",
                AsyncMock(return_value={}),
            ),
            patch(
                "services.rules_engine.repository.RulesEngineReadingsRepository."
                "get_building_context",
                AsyncMock(return_value={}),
            ),
            patch(
                "services.rules_engine.service.DomainRuleEngineService.process_readings",
                lambda self, **kwargs: [],
            ),
            patch(
                "services.stl_detection.service.STLDetectionService."
                "analyse_circuit_window_with_repo",
                return_value=[],
            ),
            patch(
                "pipelines.feature_engineering.batch_pipeline.FeatureStoreRepository"
            ) as mock_repo_cls,
        ):
            mock_repo_cls.return_value.save_features = save_features_mock

            await run_batch_feature_engineering(
                tenant_id, building_id, ts, ts + datetime.timedelta(hours=1), persist=False
            )

        save_features_mock.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_calendar_lookup_error_still_assembles_feature_without_stl_fields(self) -> None:
        """A calendar-lookup failure only skips STL enrichment for that
        circuit (matching stl_detection_activity's own precedent) -- the
        reading itself still produces a feature row, just with
        stl_residual_magnitude left None, so the pipeline degrades
        gracefully instead of silently dropping the circuit's history."""
        tenant_id, building_id, circuit_id = uuid4(), uuid4(), uuid4()
        ts = datetime.datetime(2026, 1, 5, 10, 0, tzinfo=datetime.UTC)
        reading = _make_reading(tenant_id, circuit_id, ts)

        save_features_mock = AsyncMock()
        with (
            patch(
                "pipelines.feature_engineering.batch_pipeline.get_session_factory",
                return_value=lambda: _FakeSessionCtx(),
            ),
            patch("pipelines.feature_engineering.batch_pipeline.tenant_scope", _noop_tenant_scope),
            patch(
                "services.stl_detection.repository.STLReadingsRepository.get_readings_by_circuit",
                AsyncMock(return_value={circuit_id: [reading]}),
            ),
            patch(
                "services.stl_detection.repository.TimescaleCalendarRepository."
                "fetch_calendar_entries",
                AsyncMock(return_value=[]),
            ),
            patch(
                "services.rules_engine.repository.RulesEngineReadingsRepository.get_readings",
                AsyncMock(return_value=[]),
            ),
            patch(
                "services.rules_engine.repository.RulesEngineReadingsRepository.get_circuit_types",
                AsyncMock(return_value={}),
            ),
            patch(
                "services.rules_engine.repository.RulesEngineReadingsRepository."
                "get_building_context",
                AsyncMock(return_value={}),
            ),
            patch(
                "services.rules_engine.service.DomainRuleEngineService.process_readings",
                lambda self, **kwargs: [],
            ),
            patch(
                "services.stl_detection.service.STLDetectionService."
                "analyse_circuit_window_with_repo",
                side_effect=CalendarLookupError(
                    missing_date="2026-01-05", building_id=str(building_id)
                ),
            ),
            patch(
                "pipelines.feature_engineering.batch_pipeline.FeatureStoreRepository"
            ) as mock_repo_cls,
        ):
            mock_repo_cls.return_value.save_features = save_features_mock

            features = await run_batch_feature_engineering(
                tenant_id, building_id, ts, ts + datetime.timedelta(hours=1)
            )

        assert len(features) == 1
        assert features[0].circuit_id == circuit_id
        assert features[0].stl_residual_magnitude is None
        save_features_mock.assert_awaited_once_with(features)
