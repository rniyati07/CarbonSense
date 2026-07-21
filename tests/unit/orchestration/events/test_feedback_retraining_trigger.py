"""ENG-6d: feedback-volume retraining trigger bridge tests. Mirrors
tests/unit/orchestration/events/test_analysis_trigger.py's structure
exactly.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from temporalio.exceptions import WorkflowAlreadyStartedError

from orchestration.events.kafka.feedback_retraining_trigger import handle_retraining_eligible
from orchestration.temporal.dto import RetrainingInput
from orchestration.temporal.workflows.retraining import RetrainingWorkflow
from shared.config.temporal import TemporalSettings


def _make_payload(**overrides: object) -> bytes:
    payload = {
        "event_type": "model.retraining.eligible",
        "tenant_id": str(uuid4()),
        "building_id": str(uuid4()),
        "feedback_count": 5,
        "retraining_threshold": 5,
    }
    payload.update(overrides)
    return json.dumps(payload).encode("utf-8")


class TestHandleRetrainingEligible:
    @pytest.mark.asyncio
    async def test_starts_workflow_with_correct_input(self) -> None:
        client = AsyncMock()
        settings = TemporalSettings()
        tenant_id, building_id = str(uuid4()), str(uuid4())
        raw = _make_payload(tenant_id=tenant_id, building_id=building_id, feedback_count=7)

        await handle_retraining_eligible(client, settings, raw)

        client.start_workflow.assert_awaited_once()
        call = client.start_workflow.call_args
        assert call.args[0] is RetrainingWorkflow.run
        assert call.args[1] == RetrainingInput(
            tenant_id=tenant_id, building_id=building_id, trigger="feedback_volume"
        )
        assert call.kwargs["id"] == f"retraining-feedback-{tenant_id}-{building_id}-7"
        assert call.kwargs["task_queue"] == settings.task_queue

    @pytest.mark.asyncio
    async def test_ignores_unrelated_event_type(self) -> None:
        client = AsyncMock()
        settings = TemporalSettings()
        raw = _make_payload(event_type="building.data.arrived")

        await handle_retraining_eligible(client, settings, raw)

        client.start_workflow.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_swallows_duplicate_delivery(self) -> None:
        client = AsyncMock()
        client.start_workflow.side_effect = WorkflowAlreadyStartedError(
            workflow_id="x", run_id="y", workflow_type="RetrainingWorkflow"
        )
        settings = TemporalSettings()

        await handle_retraining_eligible(client, settings, _make_payload())

    @pytest.mark.asyncio
    async def test_propagates_other_failures(self) -> None:
        client = AsyncMock()
        client.start_workflow.side_effect = RuntimeError("connection lost")
        settings = TemporalSettings()

        with pytest.raises(RuntimeError, match="connection lost"):
            await handle_retraining_eligible(client, settings, _make_payload())
