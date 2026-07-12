from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from temporalio.exceptions import ApplicationError

from orchestration.temporal.activities.analysis_stubs import data_quality_gate_activity
from orchestration.temporal.dto import AnalysisPipelineInput


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
