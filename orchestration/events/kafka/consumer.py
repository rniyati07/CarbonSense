from __future__ import annotations

import logging
from collections.abc import Callable

from confluent_kafka import Consumer, KafkaError, Message

from shared.config.kafka import KafkaSettings

logger = logging.getLogger(__name__)


class CarbonSenseKafkaConsumer:
    """Kafka consumer that deserializes events and dispatches to a handler."""

    def __init__(
        self,
        settings: KafkaSettings,
        group_id: str,
        topics: list[str],
    ) -> None:
        self._consumer = Consumer(
            {
                "bootstrap.servers": settings.bootstrap_servers,
                "group.id": group_id,
                "auto.offset.reset": "earliest",
                "enable.auto.commit": True,
            }
        )
        self._consumer.subscribe(topics)
        self._running = False

    def consume_loop(
        self,
        handler: Callable[[bytes], None],
        poll_timeout: float = 1.0,
    ) -> None:
        self._running = True
        try:
            while self._running:
                msg: Message | None = self._consumer.poll(poll_timeout)
                if msg is None:
                    continue
                if msg.error():
                    if msg.error().code() != KafkaError._PARTITION_EOF:
                        logger.error("Kafka consumer error: %s", msg.error())
                    continue
                value = msg.value()
                if value is not None:
                    handler(value)
        finally:
            self._consumer.close()

    def stop(self) -> None:
        self._running = False
