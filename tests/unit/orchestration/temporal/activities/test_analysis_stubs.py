from __future__ import annotations

import datetime
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from temporalio.exceptions import ApplicationError

from orchestration.temporal.activities.analysis_stubs import (
    data_quality_gate_activity,
    feature_assembly_activity,
    ml_ensemble_activity,
    rule_engine_activity,
    stl_detection_activity,
)
from orchestration.temporal.dto import (
    AnalysisPipelineInput,
    FeatureAssemblyOutput,
    RuleEngineOutput,
    RuleFireEvent,
    STLOutput,
)


def _patched_db(counts: dict[str, int]):
    """Patch get_session_factory + tenant_scope + the repository's
    get_status_counts() so data_quality_gate_activity runs against a fake
    result without touching a real database."""
    mock_session = AsyncMock()

    @asynccontextmanager
    async def fake_factory_cm():
        yield mock_session

    def fake_factory():
        return fake_factory_cm

    @asynccontextmanager
    async def fake_tenant_scope(session, tenant_id):
        yield session

    return (
        patch("shared.database.get_session_factory", fake_factory),
        patch("shared.auth.tenant_context.tenant_scope", fake_tenant_scope),
        patch(
            "services.ingestion.repository.DataQualityVerificationRepository.get_status_counts",
            AsyncMock(return_value=counts),
        ),
    )


class TestDataQualityGateActivity:
    @pytest.mark.asyncio
    async def test_returns_pass_when_all_readings_pass(self) -> None:
        p1, p2, p3 = _patched_db({"pass": 500})
        with p1, p2, p3:
            result = await data_quality_gate_activity(
                AnalysisPipelineInput(
                    tenant_id=str(uuid4()), building_id=str(uuid4()), correlation_id="c1"
                )
            )
        assert result.overall_status == "pass"
        assert result.pass_count == 500
        assert result.degraded_count == 0
        assert result.quarantined_count == 0

    @pytest.mark.asyncio
    async def test_returns_degraded_when_any_degraded_present(self) -> None:
        p1, p2, p3 = _patched_db({"pass": 400, "degraded": 50, "quarantined": 10})
        with p1, p2, p3:
            result = await data_quality_gate_activity(
                AnalysisPipelineInput(
                    tenant_id=str(uuid4()), building_id=str(uuid4()), correlation_id="c1"
                )
            )
        assert result.overall_status == "degraded"
        assert result.pass_count == 400
        assert result.degraded_count == 50
        assert result.quarantined_count == 10

    @pytest.mark.asyncio
    async def test_raises_non_retryable_when_quarantined_only(self) -> None:
        """TRD v2.0 3.1: a quarantined-only batch does not trigger downstream
        analysis. Must be non_retryable=True -- a plain exception here is
        retried indefinitely by Temporal's default policy (the exact bug
        already fixed once in this pipeline for confidence_calibration_activity
        and drift_detection_activity)."""
        p1, p2, p3 = _patched_db({"quarantined": 25})
        with p1, p2, p3, pytest.raises(ApplicationError) as exc_info:
            await data_quality_gate_activity(
                AnalysisPipelineInput(
                    tenant_id=str(uuid4()), building_id=str(uuid4()), correlation_id="c1"
                )
            )
        assert exc_info.value.non_retryable is True

    @pytest.mark.asyncio
    async def test_raises_non_retryable_when_window_empty(self) -> None:
        p1, p2, p3 = _patched_db({})
        with p1, p2, p3, pytest.raises(ApplicationError) as exc_info:
            await data_quality_gate_activity(
                AnalysisPipelineInput(
                    tenant_id=str(uuid4()), building_id=str(uuid4()), correlation_id="c1"
                )
            )
        assert exc_info.value.non_retryable is True


def _patched_session():
    """Same DB-bypass pattern as _patched_db(), without a repository-method
    patch baked in -- rule_engine/stl_detection tests patch different repo
    methods per test."""
    mock_session = AsyncMock()

    @asynccontextmanager
    async def fake_factory_cm():
        yield mock_session

    def fake_factory():
        return fake_factory_cm

    @asynccontextmanager
    async def fake_tenant_scope(session, tenant_id):
        yield session

    return (
        patch("shared.database.get_session_factory", fake_factory),
        patch("shared.auth.tenant_context.tenant_scope", fake_tenant_scope),
    )


class TestRuleEngineActivity:
    @pytest.mark.asyncio
    async def test_persists_findings_and_derives_rule_fires(self) -> None:
        from services.explainability.models import ExplainabilityBundle, RuleCitation
        from services.rules_engine.models import Finding

        circuit_id = uuid4()
        now = datetime.datetime.now(datetime.UTC)
        finding = Finding(
            finding_id=uuid4(),
            tenant_id=uuid4(),
            building_id=uuid4(),
            circuit_id=circuit_id,
            layer_origin="domain_rule",
            evidence_window_start=now,
            evidence_window_end=now,
            confidence=None,
            status="open",
            explainability_bundle=ExplainabilityBundle(
                finding_id=uuid4(),
                contributing_layers=["domain_rule"],
                rule_citations=[
                    RuleCitation(rule_id="hvac_after_hours_v3", version=3, citation="ASHRAE")
                ],
                evidence_window={"start": now, "end": now},
            ),
        )

        p1, p2 = _patched_session()
        save_findings_mock = AsyncMock()
        with (
            p1,
            p2,
            patch(
                "services.rules_engine.repository.RulesEngineReadingsRepository.get_readings",
                AsyncMock(return_value=[]),
            ),
            patch(
                "services.rules_engine.repository.RulesEngineReadingsRepository.get_circuit_types",
                AsyncMock(return_value={}),
            ),
            patch(
                "services.rules_engine.repository.RulesEngineReadingsRepository.get_building_context",
                AsyncMock(return_value={}),
            ),
            patch(
                "services.rules_engine.service.DomainRuleEngineService.process_readings",
                lambda self, **kwargs: [finding],
            ),
            patch(
                "services.explainability.repository.ExplainabilityRepository.save_findings",
                save_findings_mock,
            ),
        ):
            result = await rule_engine_activity(
                AnalysisPipelineInput(
                    tenant_id=str(uuid4()), building_id=str(uuid4()), correlation_id="c1"
                )
            )

        save_findings_mock.assert_awaited_once_with([finding])
        assert result.findings == [finding]
        assert len(result.rule_fires) == 1
        assert result.rule_fires[0].circuit_id == circuit_id
        assert result.rule_fires[0].rule_id == "hvac_after_hours_v3"

    @pytest.mark.asyncio
    async def test_skips_persistence_when_no_findings(self) -> None:
        p1, p2 = _patched_session()
        save_findings_mock = AsyncMock()
        with (
            p1,
            p2,
            patch(
                "services.rules_engine.repository.RulesEngineReadingsRepository.get_readings",
                AsyncMock(return_value=[]),
            ),
            patch(
                "services.rules_engine.repository.RulesEngineReadingsRepository.get_circuit_types",
                AsyncMock(return_value={}),
            ),
            patch(
                "services.rules_engine.repository.RulesEngineReadingsRepository.get_building_context",
                AsyncMock(return_value={}),
            ),
            patch(
                "services.rules_engine.service.DomainRuleEngineService.process_readings",
                lambda self, **kwargs: [],
            ),
            patch(
                "services.explainability.repository.ExplainabilityRepository.save_findings",
                save_findings_mock,
            ),
        ):
            result = await rule_engine_activity(
                AnalysisPipelineInput(
                    tenant_id=str(uuid4()), building_id=str(uuid4()), correlation_id="c1"
                )
            )

        save_findings_mock.assert_not_awaited()
        assert result.findings == []
        assert result.rule_fires == []


class TestSTLDetectionActivity:
    @pytest.mark.asyncio
    async def test_aggregates_results_across_circuits(self) -> None:
        from services.stl_detection.models import STLResidualResult

        circuit_a, circuit_b = uuid4(), uuid4()
        now = datetime.datetime.now(datetime.UTC)
        result_a = STLResidualResult(
            tenant_id=uuid4(), circuit_id=circuit_a, ts=now, kwh=1.0, day_type="business_day"
        )
        result_b = STLResidualResult(
            tenant_id=uuid4(), circuit_id=circuit_b, ts=now, kwh=2.0, day_type="weekend"
        )

        p1, p2 = _patched_session()
        with (
            p1,
            p2,
            patch(
                "services.stl_detection.repository.STLReadingsRepository.get_readings_by_circuit",
                AsyncMock(return_value={circuit_a: ["reading-a"], circuit_b: ["reading-b"]}),
            ),
            patch(
                "services.stl_detection.repository.TimescaleCalendarRepository."
                "fetch_calendar_entries",
                AsyncMock(return_value=[]),
            ),
            patch(
                "services.stl_detection.service.STLDetectionService.analyse_circuit_window_with_repo",
                side_effect=lambda readings, building_id: (
                    [result_a] if readings == ["reading-a"] else [result_b]
                ),
            ),
        ):
            result = await stl_detection_activity(
                AnalysisPipelineInput(
                    tenant_id=str(uuid4()), building_id=str(uuid4()), correlation_id="c1"
                )
            )

        assert len(result.residuals) == 2
        assert {r.circuit_id for r in result.residuals} == {circuit_a, circuit_b}

    @pytest.mark.asyncio
    async def test_skips_circuit_on_calendar_lookup_error(self) -> None:
        from services.stl_detection.exceptions import CalendarLookupError
        from services.stl_detection.models import STLResidualResult

        circuit_ok, circuit_missing = uuid4(), uuid4()
        now = datetime.datetime.now(datetime.UTC)
        result_ok = STLResidualResult(
            tenant_id=uuid4(), circuit_id=circuit_ok, ts=now, kwh=1.0, day_type="business_day"
        )

        def fake_analyse(readings, building_id):
            if readings == ["reading-missing"]:
                raise CalendarLookupError(missing_date="2026-01-01", building_id=str(building_id))
            return [result_ok]

        p1, p2 = _patched_session()
        with (
            p1,
            p2,
            patch(
                "services.stl_detection.repository.STLReadingsRepository.get_readings_by_circuit",
                AsyncMock(
                    return_value={
                        circuit_ok: ["reading-ok"],
                        circuit_missing: ["reading-missing"],
                    }
                ),
            ),
            patch(
                "services.stl_detection.repository.TimescaleCalendarRepository."
                "fetch_calendar_entries",
                AsyncMock(return_value=[]),
            ),
            patch(
                "services.stl_detection.service.STLDetectionService.analyse_circuit_window_with_repo",
                side_effect=fake_analyse,
            ),
        ):
            result = await stl_detection_activity(
                AnalysisPipelineInput(
                    tenant_id=str(uuid4()), building_id=str(uuid4()), correlation_id="c1"
                )
            )

        assert len(result.residuals) == 1
        assert result.residuals[0].circuit_id == circuit_ok


class TestFeatureAssemblyActivity:
    @pytest.mark.asyncio
    async def test_assembles_features_using_rule_and_stl_outputs(self) -> None:
        from services.ingestion.models import NormalizedReading
        from services.stl_detection.models import STLResidualResult

        tenant_id, circuit_id = uuid4(), uuid4()
        ts = datetime.datetime(2026, 1, 5, 10, 0, tzinfo=datetime.UTC)
        reading = NormalizedReading(
            tenant_id=tenant_id,
            circuit_id=circuit_id,
            ts=ts,
            kwh=5.0,
            source_system="db",
            ingestion_timestamp=ts,
            normalization_version="v1",
        )
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
        rule_fire = RuleFireEvent(circuit_id=circuit_id, ts=ts, rule_id="hvac_after_hours_v3")

        p1, p2 = _patched_session()
        with (
            p1,
            p2,
            patch(
                "services.stl_detection.repository.STLReadingsRepository.get_readings_by_circuit",
                AsyncMock(return_value={circuit_id: [reading]}),
            ),
        ):
            result = await feature_assembly_activity(
                AnalysisPipelineInput(
                    tenant_id=str(uuid4()), building_id=str(uuid4()), correlation_id="c1"
                ),
                RuleEngineOutput(findings=[], rule_fires=[rule_fire]),
                STLOutput(residuals=[stl_result]),
            )

        assert len(result.features) == 1
        feature = result.features[0]
        assert feature.circuit_id == circuit_id
        assert feature.stl_residual_magnitude == 0.4
        assert feature.day_type == "business_day"
        assert feature.rule_fire_indicators == {"hvac_after_hours_v3": True}

    @pytest.mark.asyncio
    async def test_no_readings_returns_empty_features(self) -> None:
        p1, p2 = _patched_session()
        with (
            p1,
            p2,
            patch(
                "services.stl_detection.repository.STLReadingsRepository.get_readings_by_circuit",
                AsyncMock(return_value={}),
            ),
        ):
            result = await feature_assembly_activity(
                AnalysisPipelineInput(
                    tenant_id=str(uuid4()), building_id=str(uuid4()), correlation_id="c1"
                ),
                RuleEngineOutput(findings=[], rule_fires=[]),
                STLOutput(residuals=[]),
            )

        assert result.features == []


class TestMLEnsembleActivity:
    @pytest.mark.asyncio
    async def test_scores_features_via_ensemble_serving_service(self) -> None:
        from models.feature_store.feature_set_v1 import FeatureSetV1
        from services.ml_ensemble.models import EnsembleScoreRecord

        tenant_id, circuit_id = uuid4(), uuid4()
        ts = datetime.datetime.now(datetime.UTC)
        feature = FeatureSetV1(tenant_id=tenant_id, circuit_id=circuit_id, ts=ts)
        score = EnsembleScoreRecord(
            tenant_id=tenant_id, circuit_id=circuit_id, ts=ts, ensemble_is_anomalous=True
        )

        with patch(
            "models.serving.ensemble_serving.EnsembleServingService.score",
            return_value=[score],
        ) as mock_score:
            result = await ml_ensemble_activity(
                AnalysisPipelineInput(
                    tenant_id=str(uuid4()), building_id=str(uuid4()), correlation_id="c1"
                ),
                FeatureAssemblyOutput(features=[feature]),
            )

        mock_score.assert_called_once()
        call_kwargs = mock_score.call_args.kwargs
        assert call_kwargs["features"] == [feature]
        assert result.scores == [score]

    @pytest.mark.asyncio
    async def test_no_features_returns_empty_scores(self) -> None:
        with patch(
            "models.serving.ensemble_serving.EnsembleServingService.score",
            return_value=[],
        ):
            result = await ml_ensemble_activity(
                AnalysisPipelineInput(
                    tenant_id=str(uuid4()), building_id=str(uuid4()), correlation_id="c1"
                ),
                FeatureAssemblyOutput(features=[]),
            )

        assert result.scores == []
