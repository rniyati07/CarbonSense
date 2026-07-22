"""ENG-6d — the feedback-volume retraining trigger (TRD v2.0 §6.2's third
trigger: "crossing a minimum new-labeled-feedback threshold... schedules a
retrain"). Mirrors orchestration/events/kafka/analysis_trigger.py's exact
shape: FeedbackService already publishes RetrainingEligibleEvent
(model.retraining.eligible) whenever a building's feedback count crosses
RETRAINING_THRESHOLD (services/feedback/service.py) -- nothing has ever
consumed it. This is that missing consumer.

Same idempotency mechanism as analysis_trigger.py: a deterministic
workflow ID derived from the event lets Temporal's own workflow-ID
uniqueness constraint absorb an at-least-once Kafka redelivery, with no
separate dedup store needed.
"""

from __future__ import annotations

import logging
from typing import Any

from temporalio.client import Client
from temporalio.exceptions import WorkflowAlreadyStartedError

from orchestration.events.kafka.serialization import from_json_dict
from orchestration.temporal.dto import RetrainingInput
from orchestration.temporal.workflows.retraining import RetrainingWorkflow
from shared.config.temporal import TemporalSettings

logger = logging.getLogger(__name__)

RETRAINING_ELIGIBLE_EVENT_TYPE = "model.retraining.eligible"


def _workflow_id_for(payload: dict[str, Any]) -> str:
    """Deterministic per-crossing workflow ID. Unlike analysis_trigger.py's
    per-event correlation_id, RetrainingEligibleEvent carries none -- the
    (tenant_id, building_id, feedback_count) triple is itself unique per
    genuine threshold-crossing (feedback_count only increases), so it
    serves the identical role: a duplicate/retried delivery of the same
    crossing collides on workflow ID and is absorbed by
    WorkflowAlreadyStartedError below, not double-triggering a retrain.
    """
    return (
        f"retraining-feedback-{payload['tenant_id']}-{payload['building_id']}-"
        f"{payload['feedback_count']}"
    )


async def handle_retraining_eligible(
    client: Client,
    settings: TemporalSettings,
    raw_message: bytes,
) -> None:
    payload = from_json_dict(raw_message)
    event_type = payload.get("event_type")
    if event_type != RETRAINING_ELIGIBLE_EVENT_TYPE:
        logger.warning(
            "Unexpected event_type %r on the retraining-eligible topic -- ignoring.", event_type
        )
        return

    workflow_id = _workflow_id_for(payload)
    try:
        await client.start_workflow(
            RetrainingWorkflow.run,
            RetrainingInput(
                tenant_id=payload["tenant_id"],
                building_id=payload["building_id"],
                trigger="feedback_volume",
            ),
            id=workflow_id,
            task_queue=settings.task_queue,
        )
        logger.info(
            "Started RetrainingWorkflow %s for building=%s (feedback_count=%s)",
            workflow_id,
            payload["building_id"],
            payload.get("feedback_count"),
        )
    except WorkflowAlreadyStartedError:
        logger.info(
            "RetrainingWorkflow %s already started -- duplicate delivery, skipping.",
            workflow_id,
        )
