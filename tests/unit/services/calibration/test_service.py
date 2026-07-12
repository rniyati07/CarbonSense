from __future__ import annotations

import datetime
import uuid
from collections.abc import Sequence
from unittest.mock import AsyncMock, patch

import pytest

from services.calibration.dto import (
    CalibratedFinding,
    CalibratedScore,
    FeedbackLabel,
    UncalibratedFinding,
)
from services.calibration.service import CalibrationService
from services.ml_ensemble.models import EnsembleScoreRecord


@pytest.fixture
def mock_repository() -> AsyncMock:
    repo = AsyncMock()
    # Default mocks
    repo.get_uncalibrated_findings.return_value = []
    repo.get_calibration_set.return_value = []
    repo.get_building_cold_start_flag.return_value = False
    return repo


@pytest.fixture
def tenant_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def building_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.mark.asyncio
async def test_calibration_service_no_findings(
    mock_repository: AsyncMock, tenant_id: uuid.UUID, building_id: uuid.UUID
) -> None:
    service = CalibrationService(mock_repository)
    await service.calibrate_findings(tenant_id, building_id, "corr-1")
    mock_repository.get_calibration_set.assert_not_called()
    mock_repository.save_calibrated_findings.assert_not_called()


@pytest.mark.asyncio
async def test_calibration_service_scenario_a(
    mock_repository: AsyncMock, tenant_id: uuid.UUID, building_id: uuid.UUID
) -> None:
    """
    Scenario A: cold_start = TRUE, sample count ABOVE threshold
    Expected: reduced-confidence mode, wide interval, explicit label.
    """
    finding_id = uuid.uuid4()
    mock_repository.get_uncalibrated_findings.return_value = [
        UncalibratedFinding(finding_id=finding_id, circuit_id=None, ml_anomaly_score=0.8)
    ]
    # Sample count ABOVE threshold (e.g. > 30)
    mock_repository.get_calibration_set.return_value = [
        FeedbackLabel(action="confirmed", ml_anomaly_score=0.9)
    ] * 40
    # cold_start = TRUE
    mock_repository.get_building_cold_start_flag.return_value = True

    service = CalibrationService(mock_repository)
    await service.calibrate_findings(tenant_id, building_id, "corr-1")

    mock_repository.save_calibrated_findings.assert_called_once()
    call_args = mock_repository.save_calibrated_findings.call_args
    saved_findings: Sequence[CalibratedFinding] = call_args[0][1]
    assert len(saved_findings) == 1
    assert saved_findings[0].confidence_interval_lower == 0.0
    assert saved_findings[0].confidence_interval_upper == 1.0
    assert "Low confidence" in saved_findings[0].confidence_label


@pytest.mark.asyncio
async def test_calibration_service_scenario_b(
    mock_repository: AsyncMock, tenant_id: uuid.UUID, building_id: uuid.UUID
) -> None:
    """
    Scenario B: cold_start = FALSE, sample count BELOW threshold
    Expected: reduced-confidence mode, wide interval, explicit label.
    """
    finding_id = uuid.uuid4()
    mock_repository.get_uncalibrated_findings.return_value = [
        UncalibratedFinding(finding_id=finding_id, circuit_id=None, ml_anomaly_score=0.8)
    ]
    # Sample count BELOW threshold (e.g. < 30)
    mock_repository.get_calibration_set.return_value = [
        FeedbackLabel(action="confirmed", ml_anomaly_score=0.9)
    ] * 5
    # cold_start = FALSE
    mock_repository.get_building_cold_start_flag.return_value = False

    service = CalibrationService(mock_repository)
    await service.calibrate_findings(tenant_id, building_id, "corr-1")

    mock_repository.save_calibrated_findings.assert_called_once()
    call_args = mock_repository.save_calibrated_findings.call_args
    saved_findings: Sequence[CalibratedFinding] = call_args[0][1]
    assert len(saved_findings) == 1
    assert saved_findings[0].confidence_interval_lower == 0.0
    assert saved_findings[0].confidence_interval_upper == 1.0
    assert "Low confidence" in saved_findings[0].confidence_label


@pytest.mark.asyncio
@patch("services.calibration.service.coverage_counter")
@patch("services.calibration.service.ConformalPredictor")
async def test_calibration_service_scenario_c(
    mock_predictor_cls: AsyncMock,
    mock_counter: AsyncMock,
    mock_repository: AsyncMock,
    tenant_id: uuid.UUID,
    building_id: uuid.UUID,
) -> None:
    """
    Scenario C: cold_start = FALSE, sample count ABOVE threshold
    Expected: normal calibrated confidence interval, no fallback label.
    """
    finding_id = uuid.uuid4()
    mock_repository.get_uncalibrated_findings.return_value = [
        UncalibratedFinding(finding_id=finding_id, circuit_id=None, ml_anomaly_score=0.8)
    ]
    # Sample count ABOVE threshold (e.g. > 30)
    labels = [
        FeedbackLabel(action="confirmed", ml_anomaly_score=0.9),
        FeedbackLabel(action="dismissed", ml_anomaly_score=0.1),
    ] * 20
    mock_repository.get_calibration_set.return_value = labels
    # cold_start = FALSE
    mock_repository.get_building_cold_start_flag.return_value = False

    mock_predictor_instance = mock_predictor_cls.return_value
    mock_predictor_instance.predict.return_value = [(0.7, 0.9)]

    service = CalibrationService(mock_repository)
    await service.calibrate_findings(tenant_id, building_id, "corr-1")

    mock_predictor_instance.fit.assert_called_once_with(labels)
    mock_predictor_instance.predict.assert_called_once_with([0.8])

    mock_repository.save_calibrated_findings.assert_called_once()
    call_args = mock_repository.save_calibrated_findings.call_args
    saved_findings: Sequence[CalibratedFinding] = call_args[0][1]
    assert len(saved_findings) == 1
    assert saved_findings[0].confidence_interval_lower == 0.7
    assert saved_findings[0].confidence_interval_upper == 0.9
    assert "Calibrated" in saved_findings[0].confidence_label

    mock_counter.add.assert_called_once()


def _make_score(
    *,
    if_score: float | None = None,
    ae_reconstruction_error: float | None = None,
    ensemble_is_anomalous: bool = True,
) -> EnsembleScoreRecord:
    return EnsembleScoreRecord(
        tenant_id=uuid.uuid4(),
        circuit_id=uuid.uuid4(),
        ts=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        if_score=if_score,
        ae_reconstruction_error=ae_reconstruction_error,
        ensemble_is_anomalous=ensemble_is_anomalous,
    )


@pytest.mark.asyncio
async def test_calibrate_ensemble_scores_no_anomalies_short_circuits(
    mock_repository: AsyncMock, tenant_id: uuid.UUID, building_id: uuid.UUID
) -> None:
    """Non-anomalous records never become findings, so they must never
    reach the (potentially expensive) calibration set fetch."""
    service = CalibrationService(mock_repository)
    scores = [_make_score(if_score=0.1, ensemble_is_anomalous=False)]

    result = await service.calibrate_ensemble_scores(tenant_id, building_id, scores)

    assert result == []
    mock_repository.get_calibration_set.assert_not_called()


@pytest.mark.asyncio
async def test_calibrate_ensemble_scores_does_not_persist(
    mock_repository: AsyncMock, tenant_id: uuid.UUID, building_id: uuid.UUID
) -> None:
    """calibrate_ensemble_scores() must never call save_calibrated_findings()
    -- no Finding row exists yet at this point in the pipeline (architecture
    decision 4c/4d in IMPLEMENTATION_PLAN.md)."""
    mock_repository.get_calibration_set.return_value = []
    mock_repository.get_building_cold_start_flag.return_value = True
    service = CalibrationService(mock_repository)
    scores = [_make_score(if_score=0.5)]

    result = await service.calibrate_ensemble_scores(tenant_id, building_id, scores)

    assert len(result) == 1
    assert isinstance(result[0], CalibratedScore)
    mock_repository.save_calibrated_findings.assert_not_called()


@pytest.mark.asyncio
async def test_calibrate_ensemble_scores_cold_start_matches_findings_path(
    mock_repository: AsyncMock, tenant_id: uuid.UUID, building_id: uuid.UUID
) -> None:
    """The shared _calibrate_scores() core must produce identical cold-start
    bands (0.0, 1.0) via both entry points -- this is the regression guard
    against the two entry points silently diverging."""
    mock_repository.get_calibration_set.return_value = []
    mock_repository.get_building_cold_start_flag.return_value = True
    service = CalibrationService(mock_repository)
    score = _make_score(if_score=0.42)

    result = await service.calibrate_ensemble_scores(tenant_id, building_id, [score])

    assert len(result) == 1
    assert result[0].circuit_id == score.circuit_id
    assert result[0].ts == score.ts
    assert result[0].confidence_lower == 0.0
    assert result[0].confidence_upper == 1.0
    assert result[0].is_cold_start is True


@pytest.mark.asyncio
@patch("services.calibration.service.coverage_counter")
@patch("services.calibration.service.ConformalPredictor")
async def test_calibrate_ensemble_scores_normal_calibration(
    mock_predictor_cls: AsyncMock,
    mock_counter: AsyncMock,
    mock_repository: AsyncMock,
    tenant_id: uuid.UUID,
    building_id: uuid.UUID,
) -> None:
    labels = [
        FeedbackLabel(action="confirmed", ml_anomaly_score=0.9),
        FeedbackLabel(action="dismissed", ml_anomaly_score=0.1),
    ] * 20
    mock_repository.get_calibration_set.return_value = labels
    mock_repository.get_building_cold_start_flag.return_value = False

    mock_predictor_instance = mock_predictor_cls.return_value
    mock_predictor_instance.predict.return_value = [(0.3, 0.6)]

    service = CalibrationService(mock_repository)
    score = _make_score(if_score=0.55)

    result = await service.calibrate_ensemble_scores(tenant_id, building_id, [score])

    mock_predictor_instance.fit.assert_called_once_with(labels)
    mock_predictor_instance.predict.assert_called_once_with([0.55])

    assert len(result) == 1
    assert result[0].confidence_lower == 0.3
    assert result[0].confidence_upper == 0.6
    assert result[0].is_cold_start is False
    mock_counter.add.assert_called_once()
    mock_repository.save_calibrated_findings.assert_not_called()


@pytest.mark.asyncio
async def test_calibrate_ensemble_scores_filters_non_anomalous(
    mock_repository: AsyncMock, tenant_id: uuid.UUID, building_id: uuid.UUID
) -> None:
    mock_repository.get_calibration_set.return_value = []
    mock_repository.get_building_cold_start_flag.return_value = True
    service = CalibrationService(mock_repository)
    anomalous = _make_score(if_score=0.9, ensemble_is_anomalous=True)
    non_anomalous = _make_score(if_score=0.1, ensemble_is_anomalous=False)

    result = await service.calibrate_ensemble_scores(
        tenant_id, building_id, [anomalous, non_anomalous]
    )

    assert len(result) == 1
    assert result[0].circuit_id == anomalous.circuit_id


@pytest.mark.asyncio
async def test_calibrate_ensemble_scores_score_heuristic_prefers_if_score(
    mock_repository: AsyncMock, tenant_id: uuid.UUID, building_id: uuid.UUID
) -> None:
    """PROPOSED heuristic: if_score is preferred over ae_reconstruction_error
    when both are present (see _anomaly_score() docstring)."""
    mock_repository.get_calibration_set.return_value = []
    mock_repository.get_building_cold_start_flag.return_value = True
    service = CalibrationService(mock_repository)
    score = _make_score(if_score=0.77, ae_reconstruction_error=3.5)

    result = await service.calibrate_ensemble_scores(tenant_id, building_id, [score])

    # Cold start band is score-independent, so assert via the fallback path
    # instead: rerun with if_score=None and confirm ae_reconstruction_error
    # is used as a distinguishing smoke check on _anomaly_score() directly.
    from services.calibration.service import _anomaly_score

    assert _anomaly_score(score) == 0.77
    assert _anomaly_score(_make_score(ae_reconstruction_error=3.5)) == 3.5
    assert _anomaly_score(_make_score()) == 0.0
    assert len(result) == 1
