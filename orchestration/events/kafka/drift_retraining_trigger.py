"""ENG-6d — the drift-detection retraining trigger (TRD v2.0 §6.2's second
trigger: "a model.drift.detected event... schedules an out-of-cycle
retrain rather than waiting for the next calendar slot").

Deserializes differently than analysis_trigger.py/feedback_retraining_trigger.py:
KafkaDriftEventPublisher (services/drift_detection/event_publisher.py)
publishes DriftEventPayload via a raw confluent_kafka Producer and
json.dumps(payload.model_dump(mode="json")) -- not through the BaseEvent/
to_json_bytes scheme building.data.arrived and model.retraining.eligible
use, and DriftEventPayload carries no event_type field. Every message on
topic_model_drift_detected is unconditionally a real drift event: the
publisher is only ever called when drift_result.status == DriftStatus.DRIFTING
(orchestration/temporal/activities/drift_detection_stub.py), so this
consumer does not need to filter further.
"""

from __future__ import annotations

import json
import logging

from temporalio.client import Client
from temporalio.exceptions import WorkflowAlreadyStartedError

from orchestration.temporal.dto import RetrainingInput
from orchestration.temporal.workflows.retraining import RetrainingWorkflow
from services.drift_detection.models import DriftEventPayload
from shared.config.temporal import TemporalSettings

logger = logging.getLogger(__name__)


def _workflow_id_for(payload: DriftEventPayload) -> str:
    """Deterministic per-drift-evaluation workflow ID, matching the same
    collide-on-duplicate-delivery idempotency pattern as
    analysis_trigger.py/feedback_retraining_trigger.py. Drift is evaluated
    on a schedule (DriftDetectionWorkflow), so timestamp (to the second)
    is what makes two genuinely distinct drift evaluations produce
    distinct workflow IDs, while a redelivery of the *same* message
    (identical timestamp) collides and is absorbed below.
    """
    return (
        f"retraining-drift-{payload.tenant_id}-{payload.building_id}-"
        f"{payload.timestamp.isoformat()}"
    )


async def handle_drift_detected(
    client: Client,
    settings: TemporalSettings,
    raw_message: bytes,
) -> None:
    payload = DriftEventPayload.model_validate(json.loads(raw_message))

    workflow_id = _workflow_id_for(payload)
    try:
        await client.start_workflow(
            RetrainingWorkflow.run,
            RetrainingInput(
                tenant_id=str(payload.tenant_id),
                building_id=str(payload.building_id),
                trigger="drift",
            ),
            id=workflow_id,
            task_queue=settings.task_queue,
        )
        logger.info(
            "Started RetrainingWorkflow %s for building=%s (drift trend=%s magnitude=%s)",
            workflow_id,
            payload.building_id,
            payload.trend_direction,
            payload.magnitude,
        )
    except WorkflowAlreadyStartedError:
        logger.info(
            "RetrainingWorkflow %s already started -- duplicate delivery, skipping.",
            workflow_id,
        )
