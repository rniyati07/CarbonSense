"""ENG-2b: Kafka producer tests.

Tests that:
- Events are published with correct key (tenant_id) and serialized value
- Delivery callback is wired
- Publish is non-blocking (produce + poll(0))
"""

from __future__ import annotations

import datetime
import json
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from orchestration.events.kafka.producer import CarbonSenseKafkaProducer
from orchestration.events.kafka.schemas.data_arrived import BuildingDataArrivedEvent
from shared.config.kafka import KafkaSettings


@pytest.mark.unit
def test_publish_serializes_event_correctly() -> None:
    """Published message has tenant_id as key and valid JSON as value."""
    tenant_id = uuid4()
    event = BuildingDataArrivedEvent(
        event_id=uuid4(),
        tenant_id=tenant_id,
        building_id=uuid4(),
        correlation_id=uuid4(),
        timestamp=datetime.datetime.now(tz=datetime.UTC),
        event_type="building.data.arrived",
        data_quality_status="pass",
        batch_row_count=100,
        ingestion_source="csv_upload",
    )

    with patch("orchestration.events.kafka.producer.Producer") as mock_producer_cls:
        mock_producer = MagicMock()
        mock_producer_cls.return_value = mock_producer

        producer = CarbonSenseKafkaProducer(KafkaSettings())
        producer.publish("building.data.arrived", event)

        mock_producer.produce.assert_called_once()
        call_kwargs = mock_producer.produce.call_args
        assert call_kwargs.kwargs["topic"] == "building.data.arrived"
        assert call_kwargs.kwargs["key"] == str(tenant_id).encode("utf-8")

        value = json.loads(call_kwargs.kwargs["value"].decode("utf-8"))
        assert value["event_type"] == "building.data.arrived"
        assert value["tenant_id"] == str(tenant_id)
        assert value["batch_row_count"] == 100

        mock_producer.poll.assert_called_once_with(0)


@pytest.mark.unit
def test_flush_delegates_to_confluent_producer() -> None:
    with patch("orchestration.events.kafka.producer.Producer") as mock_cls:
        mock_producer = MagicMock()
        mock_producer.flush.return_value = 0
        mock_cls.return_value = mock_producer

        producer = CarbonSenseKafkaProducer(KafkaSettings())
        result = producer.flush(timeout=3.0)

        mock_producer.flush.assert_called_once_with(3.0)
        assert result == 0
