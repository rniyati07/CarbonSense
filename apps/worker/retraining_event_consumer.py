"""ENG-6d — process entrypoint for the drift-detection and feedback-volume
retraining triggers.

Mirrors apps/worker/event_consumer.py's exact shape (ENG-5 prerequisite)
but runs two CarbonSenseKafkaConsumer instances concurrently, one per
topic -- CarbonSenseKafkaConsumer.consume_loop()'s handler callback
receives only the message value, not which topic it arrived on, so one
consumer per topic (each with its own dedicated handler) is simpler and
lower-risk than extending that already-in-use infrastructure to pass
topic metadata through. Both run in this same process via asyncio.gather
over two run_in_executor calls, exactly the same blocking-poll-loop-in-a-
thread pattern event_consumer.py already established.

Runs as its own long-lived process, separate from apps/worker/main.py's
Temporal Worker and from apps/worker/event_consumer.py -- this process
only consumes Kafka and starts RetrainingWorkflow executions; it does not
execute any workflow/activity code itself.
"""

from __future__ import annotations

import asyncio
import logging

from temporalio.client import Client

from apps.worker.config import build_tls_config
from orchestration.events.kafka.consumer import CarbonSenseKafkaConsumer
from orchestration.events.kafka.drift_retraining_trigger import handle_drift_detected
from orchestration.events.kafka.feedback_retraining_trigger import handle_retraining_eligible
from shared.config.kafka import KafkaSettings
from shared.config.temporal import TemporalSettings

logger = logging.getLogger(__name__)


async def run_consumer() -> None:
    kafka_settings = KafkaSettings()
    temporal_settings = TemporalSettings()

    client = await Client.connect(
        temporal_settings.host,
        namespace=temporal_settings.namespace,
        tls=build_tls_config(temporal_settings),
    )

    drift_consumer = CarbonSenseKafkaConsumer(
        settings=kafka_settings,
        group_id="retraining-drift-trigger",
        topics=[kafka_settings.topic_model_drift_detected],
    )
    feedback_consumer = CarbonSenseKafkaConsumer(
        settings=kafka_settings,
        group_id="retraining-feedback-trigger",
        topics=[kafka_settings.topic_retraining_eligible],
    )

    loop = asyncio.get_running_loop()

    def drift_handler(raw_message: bytes) -> None:
        future = asyncio.run_coroutine_threadsafe(
            handle_drift_detected(client, temporal_settings, raw_message), loop
        )
        future.result()

    def feedback_handler(raw_message: bytes) -> None:
        future = asyncio.run_coroutine_threadsafe(
            handle_retraining_eligible(client, temporal_settings, raw_message), loop
        )
        future.result()

    await asyncio.gather(
        loop.run_in_executor(None, drift_consumer.consume_loop, drift_handler),
        loop.run_in_executor(None, feedback_consumer.consume_loop, feedback_handler),
    )


def main() -> None:
    asyncio.run(run_consumer())


if __name__ == "__main__":
    main()
