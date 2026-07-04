"""ENG-2b integration test: producer → real Kafka broker → consumer.

Proves end-to-end event delivery through an actual Kafka instance.
Requires Docker. Run with: pytest -m integration tests/integration/
"""

from __future__ import annotations

import datetime
import json
import threading
from uuid import uuid4

import pytest

from orchestration.events.kafka.producer import CarbonSenseKafkaProducer
from orchestration.events.kafka.schemas.data_arrived import BuildingDataArrivedEvent
from shared.config.kafka import KafkaSettings

try:
    from testcontainers.kafka import KafkaContainer

    HAS_TESTCONTAINERS = True
except ImportError:
    HAS_TESTCONTAINERS = False

try:
    import docker

    docker.from_env().ping()
    HAS_DOCKER = True
except Exception:
    HAS_DOCKER = False

pytestmark = pytest.mark.integration
skip_reason = (
    "testcontainers[kafka] not installed" if not HAS_TESTCONTAINERS else "Docker not available"
)
skip_if_no_infra = pytest.mark.skipif(
    not (HAS_TESTCONTAINERS and HAS_DOCKER),
    reason=skip_reason,
)


@skip_if_no_infra
def test_kafka_produce_consume_roundtrip() -> None:
    """Publish a BuildingDataArrivedEvent and consume it from a real broker."""
    with KafkaContainer() as kafka:
        bootstrap = kafka.get_bootstrap_server()
        topic = "building.data.arrived"
        settings = KafkaSettings(bootstrap_servers=bootstrap, topic_data_arrived=topic)

        tenant_id = uuid4()
        event = BuildingDataArrivedEvent(
            event_id=uuid4(),
            tenant_id=tenant_id,
            building_id=uuid4(),
            correlation_id=uuid4(),
            timestamp=datetime.datetime.now(tz=datetime.UTC),
            event_type="building.data.arrived",
            data_quality_status="pass",
            batch_row_count=42,
            ingestion_source="csv_upload",
        )

        # Publish
        producer = CarbonSenseKafkaProducer(settings)
        producer.publish(topic, event)
        remaining = producer.flush(timeout=10.0)
        assert remaining == 0, f"Failed to deliver {remaining} message(s)"

        # Consume via CarbonSenseKafkaConsumer
        from orchestration.events.kafka.consumer import CarbonSenseKafkaConsumer

        received: list[dict] = []
        consumer = CarbonSenseKafkaConsumer(
            settings,
            group_id="test-roundtrip",
            topics=[topic],
        )

        def handler(data: bytes) -> None:
            received.append(json.loads(data.decode("utf-8")))
            consumer.stop()

        # Run consume loop in a thread with a timeout
        t = threading.Thread(
            target=consumer.consume_loop,
            kwargs={"handler": handler, "poll_timeout": 1.0},
        )
        t.start()
        t.join(timeout=30)
        if t.is_alive():
            consumer.stop()
            t.join(timeout=5)

        assert len(received) == 1, f"Expected 1 message, got {len(received)}"
        msg = received[0]
        assert msg["event_type"] == "building.data.arrived"
        assert msg["tenant_id"] == str(tenant_id)
        assert msg["data_quality_status"] == "pass"
        assert msg["batch_row_count"] == 42
        assert msg["ingestion_source"] == "csv_upload"
        # Verify all 5 mandatory fields present
        for field in ("event_id", "tenant_id", "building_id", "correlation_id", "timestamp"):
            assert field in msg, f"Missing required field: {field}"
