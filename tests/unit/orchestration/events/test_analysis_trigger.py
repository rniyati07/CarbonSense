"""ENG-5 prerequisite: ING -> EVT -> WF bridge tests.

Tests that:
- A building.data.arrived event starts AnalysisPipelineWorkflow with the
  right input and a deterministic, per-event workflow ID.
- Any other event_type is ignored, not treated as an error.
- A duplicate delivery (WorkflowAlreadyStartedError) is swallowed, not
  raised -- this is the idempotency property the module relies on.
- Any other failure to start the workflow propagates (is not swallowed).
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from temporalio.exceptions import WorkflowAlreadyStartedError

from orchestration.events.kafka.analysis_trigger import handle_data_arrived
from orchestration.temporal.dto import AnalysisPipelineInput
from orchestration.temporal.workflows.analysis_pipeline import AnalysisPipelineWorkflow
from shared.config.temporal import TemporalSettings


def _make_payload(**overrides: object) -> bytes:
    payload = {
        "event_type": "building.data.arrived",
        "tenant_id": str(uuid4()),
        "building_id": str(uuid4()),
        "correlation_id": str(uuid4()),
    }
    payload.update(overrides)
    return json.dumps(payload).encode("utf-8")


class TestHandleDataArrived:
    @pytest.mark.asyncio
    async def test_starts_workflow_with_correct_input(self) -> None:
        client = AsyncMock()
        settings = TemporalSettings()
        tenant_id, building_id, correlation_id = str(uuid4()), str(uuid4()), str(uuid4())
        raw = _make_payload(
            tenant_id=tenant_id, building_id=building_id, correlation_id=correlation_id
        )

        await handle_data_arrived(client, settings, raw)

        client.start_workflow.assert_awaited_once()
        call = client.start_workflow.call_args
        assert call.args[0] is AnalysisPipelineWorkflow.run
        assert call.args[1] == AnalysisPipelineInput(
            tenant_id=tenant_id, building_id=building_id, correlation_id=correlation_id
        )
        assert call.kwargs["id"] == f"analysis-{tenant_id}-{building_id}-{correlation_id}"
        assert call.kwargs["task_queue"] == settings.task_queue

    @pytest.mark.asyncio
    async def test_ignores_unrelated_event_type(self) -> None:
        client = AsyncMock()
        settings = TemporalSettings()
        raw = _make_payload(event_type="model.retraining.eligible")

        await handle_data_arrived(client, settings, raw)

        client.start_workflow.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_swallows_duplicate_delivery(self) -> None:
        client = AsyncMock()
        client.start_workflow.side_effect = WorkflowAlreadyStartedError(
            workflow_id="x", run_id="y", workflow_type="AnalysisPipelineWorkflow"
        )
        settings = TemporalSettings()

        # Must not raise.
        await handle_data_arrived(client, settings, _make_payload())

    @pytest.mark.asyncio
    async def test_propagates_other_failures(self) -> None:
        client = AsyncMock()
        client.start_workflow.side_effect = RuntimeError("connection lost")
        settings = TemporalSettings()

        with pytest.raises(RuntimeError, match="connection lost"):
            await handle_data_arrived(client, settings, _make_payload())
