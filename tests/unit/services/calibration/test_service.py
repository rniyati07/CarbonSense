from __future__ import annotations

import uuid
from typing import Sequence
from unittest.mock import AsyncMock, patch

import pytest

from services.calibration.dto import CalibratedFinding, FeedbackLabel, UncalibratedFinding
from services.calibration.service import CalibrationService


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
    saved_findings: Sequence[CalibratedFinding] = mock_repository.save_calibrated_findings.call_args[0][1]
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
    saved_findings: Sequence[CalibratedFinding] = mock_repository.save_calibrated_findings.call_args[0][1]
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
    saved_findings: Sequence[CalibratedFinding] = mock_repository.save_calibrated_findings.call_args[0][1]
    assert len(saved_findings) == 1
    assert saved_findings[0].confidence_interval_lower == 0.7
    assert saved_findings[0].confidence_interval_upper == 0.9
    assert "Calibrated" in saved_findings[0].confidence_label

    mock_counter.add.assert_called_once()
