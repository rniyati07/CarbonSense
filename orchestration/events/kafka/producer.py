from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from confluent_kafka import KafkaError, Producer

from orchestration.events.kafka.schemas.base import BaseEvent
from orchestration.events.kafka.serialization import to_json_bytes
from shared.config.kafka import KafkaSettings

logger = logging.getLogger(__name__)


@runtime_checkable
class EventPublisher(Protocol):
    def publish(self, topic: str, event: BaseEvent) -> None: ...
    def flush(self, timeout: float = 5.0) -> int: ...


class CarbonSenseKafkaProducer:
    """Non-blocking Kafka producer wrapping confluent-kafka.

    produce() buffers locally; librdkafka's background thread sends.
    Call flush() at shutdown.
    """

    def __init__(self, settings: KafkaSettings) -> None:
        self._producer = Producer(
            {
                "bootstrap.servers": settings.bootstrap_servers,
                "client.id": "carbonsense-producer",
            }
        )

    def _delivery_callback(self, err: KafkaError | None, msg: object) -> None:
        if err is not None:
            logger.error("Event delivery failed: %s", err)

    def publish(self, topic: str, event: BaseEvent) -> None:
        self._producer.produce(
            topic=topic,
            key=str(event.tenant_id).encode("utf-8"),
            value=to_json_bytes(event),
            callback=self._delivery_callback,
        )
        self._producer.poll(0)

    def flush(self, timeout: float = 5.0) -> int:
        return self._producer.flush(timeout)
