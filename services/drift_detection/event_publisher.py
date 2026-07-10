from __future__ import annotations

import json
from typing import Protocol

import structlog
from confluent_kafka import KafkaException, Producer

from services.drift_detection.models import DriftEventPayload
from shared.config.kafka import KafkaSettings


class DriftEventPublisher(Protocol):
    def publish_drift_detected(self, payload: DriftEventPayload) -> None:
        """Publishes the model.drift.detected event."""
        ...

    def publish_customer_notification(self, tenant_id: str, building_id: str) -> None:
        """Publishes a customer-facing notification that the building baseline may be stale."""
        ...

class KafkaDriftEventPublisher:
    """Implementation of DriftEventPublisher using confluent-kafka."""

    def __init__(self, settings: KafkaSettings | None = None) -> None:
        self.settings = settings or KafkaSettings()
        self._logger = structlog.get_logger(__name__)
        # In a real production setup, the producer should be a singleton injected here.
        # Initializing here to demonstrate the dependency boundary.
        self._producer = Producer({"bootstrap.servers": self.settings.bootstrap_servers})

    def publish_drift_detected(self, payload: DriftEventPayload) -> None:
        # Was hardcoded inline; wired to shared config (pre-ENG-4 integration
        # audit) so producer and consumer can't drift apart on the topic
        # string, and so this matches the same fix applied to eng-3h's
        # retraining_eligible topic.
        topic = self.settings.topic_model_drift_detected
        data = payload.model_dump(mode='json')

        try:
            self._producer.produce(
                topic,
                key=str(payload.building_id).encode("utf-8"),
                value=json.dumps(data).encode("utf-8"),
            )
            self._producer.poll(0)
            self._logger.info(
                "Published drift detected event", building_id=str(payload.building_id)
            )
        except KafkaException as e:
            self._logger.error(
                "Failed to publish drift detected event",
                error=str(e),
                building_id=str(payload.building_id),
            )
            raise  # Raise so Temporal can retry

    def publish_customer_notification(self, tenant_id: str, building_id: str) -> None:
        # TRD specifies raising a customer-facing notice. We mock this as another event
        # or it could be a call to a notifications service endpoint.
        topic = self.settings.topic_customer_notification
        message = {
            "tenant_id": tenant_id,
            "building_id": building_id,
            "notification_type": "baseline_stale",
            "message": "The building's baseline behavior has drifted and may be stale.",
        }
        try:
            self._producer.produce(
                topic,
                key=str(building_id).encode("utf-8"),
                value=json.dumps(message).encode("utf-8"),
            )
            self._producer.poll(0)
            self._logger.info("Published customer notification", building_id=building_id)
        except KafkaException as e:
            self._logger.error(
                "Failed to publish customer notification",
                error=str(e),
                building_id=building_id,
            )
            raise

    def flush(self) -> None:
        self._producer.flush()
