"""ENG-5 prerequisite — the ING -> EVT -> WF bridge (TRD v2.0 §1.2/§1.3).

Ingestion publishes `building.data.arrived`; this module is the *consumer*-
side handler that starts AnalysisPipelineWorkflow in response. The API
layer (ENG-5b's Ingestion API) publishes only and never calls
start_workflow() directly -- that decoupling (a burst of uploads doesn't
block on pipeline capacity; a slow pipeline doesn't block ingestion acks)
is the entire point of putting Kafka between the two, per TRD's own
architecture diagram. Skipping this module and having the API start the
workflow directly would silently defeat that decoupling.

Run as a process via apps/worker/event_consumer.py, which wires a real
Kafka consumer + Temporal client to handle_data_arrived() below.
"""

from __future__ import annotations

import logging
from typing import Any

from temporalio.client import Client
from temporalio.exceptions import WorkflowAlreadyStartedError

from orchestration.events.kafka.serialization import from_json_dict
from orchestration.temporal.dto import AnalysisPipelineInput
from orchestration.temporal.workflows.analysis_pipeline import AnalysisPipelineWorkflow
from shared.config.temporal import TemporalSettings

logger = logging.getLogger(__name__)

DATA_ARRIVED_EVENT_TYPE = "building.data.arrived"


def _workflow_id_for(payload: dict[str, Any]) -> str:
    """Deterministic per-event workflow ID.

    DataQualityEventPublisher mints a fresh correlation_id per published
    batch, so this ID is unique per real ingestion event -- and Temporal's
    own workflow-ID uniqueness constraint is what makes a duplicate/retried
    Kafka delivery of the *same* message a no-op (WorkflowAlreadyStartedError,
    caught below) rather than a second pipeline run, without this consumer
    needing to implement its own dedup store.
    """
    return f"analysis-{payload['tenant_id']}-{payload['building_id']}-{payload['correlation_id']}"


async def handle_data_arrived(
    client: Client,
    settings: TemporalSettings,
    raw_message: bytes,
) -> None:
    """Deserialize one Kafka message; if it's a building.data.arrived event,
    start AnalysisPipelineWorkflow. Any other event_type found on this topic
    (there should be none today, but the topic's schema may grow) is logged
    and ignored, not treated as an error.
    """
    payload = from_json_dict(raw_message)
    event_type = payload.get("event_type")
    if event_type != DATA_ARRIVED_EVENT_TYPE:
        logger.warning(
            "Unexpected event_type %r on the data-arrived topic -- ignoring.", event_type
        )
        return

    workflow_id = _workflow_id_for(payload)
    try:
        await client.start_workflow(
            AnalysisPipelineWorkflow.run,
            AnalysisPipelineInput(
                tenant_id=payload["tenant_id"],
                building_id=payload["building_id"],
                correlation_id=payload["correlation_id"],
            ),
            id=workflow_id,
            task_queue=settings.task_queue,
        )
        logger.info(
            "Started AnalysisPipelineWorkflow %s for building=%s",
            workflow_id,
            payload["building_id"],
        )
    except WorkflowAlreadyStartedError:
        # Expected on a duplicate/retried delivery of the same event --
        # not an error, just proof the idempotency property described
        # above is working.
        logger.info(
            "AnalysisPipelineWorkflow %s already started -- duplicate delivery, skipping.",
            workflow_id,
        )
