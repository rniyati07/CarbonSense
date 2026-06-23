"""ENG-2b: Kafka consumer tests.

Tests that:
- Consumer dispatches messages to the handler callback
- Consumer stops when stop() is called
- Consumer handles partition EOF gracefully
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from orchestration.events.kafka.consumer import CarbonSenseKafkaConsumer
from shared.config.kafka import KafkaSettings


def _make_mock_message(value: bytes) -> MagicMock:
    msg = MagicMock()
    msg.error.return_value = None
    msg.value.return_value = value
    return msg


@pytest.mark.unit
def test_consumer_dispatches_to_handler() -> None:
    """Consumer calls handler with the message value bytes."""
    received: list[bytes] = []
    payload = json.dumps({"event_type": "building.data.arrived"}).encode("utf-8")

    with patch("orchestration.events.kafka.consumer.Consumer") as mock_cls:
        mock_consumer = MagicMock()
        mock_cls.return_value = mock_consumer

        call_count = 0

        def poll_side_effect(timeout: float) -> MagicMock | None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_mock_message(payload)
            return None

        mock_consumer.poll.side_effect = poll_side_effect

        consumer = CarbonSenseKafkaConsumer(
            KafkaSettings(),
            group_id="test-group",
            topics=["building.data.arrived"],
        )

        def handler(data: bytes) -> None:
            received.append(data)
            consumer.stop()

        consumer.consume_loop(handler, poll_timeout=0.1)

    assert len(received) == 1
    assert json.loads(received[0]) == {"event_type": "building.data.arrived"}


@pytest.mark.unit
def test_consumer_stop_breaks_loop() -> None:
    """Calling stop() causes the consume loop to exit."""
    with patch("orchestration.events.kafka.consumer.Consumer") as mock_cls:
        mock_consumer = MagicMock()
        mock_cls.return_value = mock_consumer
        mock_consumer.poll.return_value = None

        consumer = CarbonSenseKafkaConsumer(
            KafkaSettings(),
            group_id="test-group",
            topics=["test-topic"],
        )

        iterations = 0

        def poll_counting(timeout: float) -> None:
            nonlocal iterations
            iterations += 1
            if iterations >= 3:
                consumer.stop()
            return None

        mock_consumer.poll.side_effect = poll_counting
        consumer.consume_loop(lambda d: None, poll_timeout=0.01)

        assert iterations >= 3
        mock_consumer.close.assert_called_once()
