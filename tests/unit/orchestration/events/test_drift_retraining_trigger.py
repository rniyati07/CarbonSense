"""ENG-6d: drift-detection retraining trigger bridge tests. Unlike
test_analysis_trigger.py/test_feedback_retraining_trigger.py, there is no
"ignores unrelated event_type" case -- DriftEventPayload carries no
event_type field (see drift_retraining_trigger.py's module docstring for
why), so every message on this dedicated topic is handled unconditionally.
"""

from __future__ import annotations

import datetime
import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from temporalio.exceptions import WorkflowAlreadyStartedError

from orchestration.events.kafka.drift_retraining_trigger import handle_drift_detected
from orchestration.temporal.dto import RetrainingInput
from orchestration.temporal.workflows.retraining import RetrainingWorkflow
from shared.config.temporal import TemporalSettings


def _make_payload(**overrides: object) -> bytes:
    payload = {
        "tenant_id": str(uuid4()),
        "building_id": str(uuid4()),
        "trend_direction": "increasing",
        "magnitude": 0.42,
        "timestamp": datetime.datetime(2026, 1, 5, tzinfo=datetime.UTC).isoformat(),
    }
    payload.update(overrides)
    return json.dumps(payload).encode("utf-8")


class TestHandleDriftDetected:
    @pytest.mark.asyncio
    async def test_starts_workflow_with_correct_input(self) -> None:
        client = AsyncMock()
        settings = TemporalSettings()
        tenant_id, building_id = str(uuid4()), str(uuid4())
        raw = _make_payload(tenant_id=tenant_id, building_id=building_id)

        await handle_drift_detected(client, settings, raw)

        client.start_workflow.assert_awaited_once()
        call = client.start_workflow.call_args
        assert call.args[0] is RetrainingWorkflow.run
        assert call.args[1] == RetrainingInput(
            tenant_id=tenant_id, building_id=building_id, trigger="drift"
        )
        assert call.kwargs["id"].startswith(f"retraining-drift-{tenant_id}-{building_id}-")
        assert call.kwargs["task_queue"] == settings.task_queue

    @pytest.mark.asyncio
    async def test_swallows_duplicate_delivery(self) -> None:
        client = AsyncMock()
        client.start_workflow.side_effect = WorkflowAlreadyStartedError(
            workflow_id="x", run_id="y", workflow_type="RetrainingWorkflow"
        )
        settings = TemporalSettings()

        await handle_drift_detected(client, settings, _make_payload())

    @pytest.mark.asyncio
    async def test_propagates_other_failures(self) -> None:
        client = AsyncMock()
        client.start_workflow.side_effect = RuntimeError("connection lost")
        settings = TemporalSettings()

        with pytest.raises(RuntimeError, match="connection lost"):
            await handle_drift_detected(client, settings, _make_payload())

    @pytest.mark.asyncio
    async def test_same_timestamp_produces_same_workflow_id(self) -> None:
        """Two deliveries of the *same* drift evaluation (identical
        timestamp) must collide on workflow ID -- that collision is the
        idempotency mechanism, not a bug."""
        client = AsyncMock()
        settings = TemporalSettings()
        raw = _make_payload()

        await handle_drift_detected(client, settings, raw)
        first_id = client.start_workflow.call_args.kwargs["id"]

        await handle_drift_detected(client, settings, raw)
        second_id = client.start_workflow.call_args.kwargs["id"]

        assert first_id == second_id
