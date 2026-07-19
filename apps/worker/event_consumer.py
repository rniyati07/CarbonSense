"""ENG-5 prerequisite — process entrypoint for the ING -> EVT -> WF bridge.

Wires the existing CarbonSenseKafkaConsumer (orchestration/events/kafka/
consumer.py -- generic infrastructure that, until this module, was never
actually instantiated anywhere) to a real Temporal client and
handle_data_arrived() (orchestration/events/kafka/analysis_trigger.py).

Runs as its own long-lived process, separate from apps/worker/main.py's
Temporal Worker -- this process only consumes Kafka and starts workflows;
it does not execute any workflow/activity code itself.
"""

from __future__ import annotations

import asyncio
import logging

from temporalio.client import Client

from apps.worker.config import build_tls_config
from orchestration.events.kafka.analysis_trigger import handle_data_arrived
from orchestration.events.kafka.consumer import CarbonSenseKafkaConsumer
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

    consumer = CarbonSenseKafkaConsumer(
        settings=kafka_settings,
        group_id="analysis-pipeline-trigger",
        topics=[kafka_settings.topic_data_arrived],
    )

    loop = asyncio.get_running_loop()

    def handler(raw_message: bytes) -> None:
        # CarbonSenseKafkaConsumer.consume_loop() is a blocking, synchronous
        # poll loop (reused as-is, not reimplemented), run below via
        # run_in_executor -- i.e. in a worker thread, not the main loop's
        # thread. handle_data_arrived() is async because it awaits a
        # Temporal client call, so it must be scheduled back onto the main
        # loop with run_coroutine_threadsafe() and waited on synchronously
        # here; calling run_until_complete() on the main loop from this
        # thread would raise (a loop can only be driven by its own thread).
        future = asyncio.run_coroutine_threadsafe(
            handle_data_arrived(client, temporal_settings, raw_message), loop
        )
        future.result()

    await loop.run_in_executor(None, consumer.consume_loop, handler)


def main() -> None:
    asyncio.run(run_consumer())


if __name__ == "__main__":
    main()
