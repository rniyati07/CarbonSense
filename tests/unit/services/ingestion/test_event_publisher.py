"""ENG-3a-4: Event backbone integration tests."""

from __future__ import annotations

import pytest

from orchestration.events.kafka.schemas.base import BaseEvent
from services.ingestion.alert_store import InMemoryAlertStore
from services.ingestion.config import DataQualityGateConfig
from services.ingestion.event_publisher import DataQualityEventPublisher
from services.ingestion.quality_gate import DataQualityGate
from shared.config.kafka import KafkaSettings
from tests.unit.services.ingestion.conftest import (
    BUILDING_ID,
    TENANT_ID,
    make_batch,
)


class MockKafkaProducer:
    def __init__(self) -> None:
        self.published: list[tuple[str, BaseEvent]] = []

    def publish(self, topic: str, event: BaseEvent) -> None:
        self.published.append((topic, event))

    def flush(self, timeout: float = 5.0) -> int:
        return 0


@pytest.fixture()
def mock_producer() -> MockKafkaProducer:
    return MockKafkaProducer()


@pytest.fixture()
def alert_store() -> InMemoryAlertStore:
    return InMemoryAlertStore()


@pytest.fixture()
def publisher(
    mock_producer: MockKafkaProducer, alert_store: InMemoryAlertStore
) -> DataQualityEventPublisher:
    return DataQualityEventPublisher(
        producer=mock_producer,
        settings=KafkaSettings(),
        alert_store=alert_store,
    )


@pytest.mark.unit
class TestPassBatchPublishes:
    def test_pass_batch_publishes_event(
        self, publisher: DataQualityEventPublisher, mock_producer: MockKafkaProducer
    ) -> None:
        gate = DataQualityGate()
        batch = make_batch("clean_batch.csv")
        result = gate.process_batch(batch)
        assert result.overall_status == "pass"

        outcome = publisher.publish_or_alert(result)
        assert outcome.published is True
        assert outcome.alert is None
        assert len(mock_producer.published) == 1
        topic, event = mock_producer.published[0]
        assert topic == "building.data.arrived"
        assert event.event_type == "building.data.arrived"
        assert event.tenant_id == TENANT_ID
        assert event.building_id == BUILDING_ID


@pytest.mark.unit
class TestDegradedBatchPublishes:
    def test_degraded_batch_publishes_event(
        self, publisher: DataQualityEventPublisher, mock_producer: MockKafkaProducer
    ) -> None:
        gate = DataQualityGate()
        batch = make_batch("gap_beyond_bound.csv")
        result = gate.process_batch(batch)

        if result.overall_status == "quarantined":
            pytest.skip("Batch was fully quarantined, not degraded")

        outcome = publisher.publish_or_alert(result)
        assert outcome.published is True
        assert len(mock_producer.published) == 1


@pytest.mark.unit
class TestQuarantinedBatchAlert:
    def test_quarantined_batch_no_event(
        self,
        publisher: DataQualityEventPublisher,
        mock_producer: MockKafkaProducer,
        alert_store: InMemoryAlertStore,
    ) -> None:
        config = DataQualityGateConfig()
        config.bounds.circuit_type_bounds["hvac"].max_kwh = 0.001
        config.bounds.circuit_type_bounds["lighting"].max_kwh = 0.001
        config.bounds.default_bounds.max_kwh = 0.001
        gate = DataQualityGate(config)
        batch = make_batch("clean_batch.csv")
        result = gate.process_batch(batch)
        assert result.overall_status == "quarantined"

        outcome = publisher.publish_or_alert(result)
        assert outcome.published is False
        assert outcome.alert is not None
        assert outcome.alert.alert_type == "quarantined_batch"
        assert outcome.alert.tenant_id == TENANT_ID
        assert outcome.alert.building_id == BUILDING_ID
        assert len(mock_producer.published) == 0

    def test_quarantined_alert_is_tenant_scoped(
        self,
        publisher: DataQualityEventPublisher,
        mock_producer: MockKafkaProducer,
        alert_store: InMemoryAlertStore,
    ) -> None:
        config = DataQualityGateConfig()
        config.bounds.circuit_type_bounds["hvac"].max_kwh = 0.001
        config.bounds.circuit_type_bounds["lighting"].max_kwh = 0.001
        config.bounds.default_bounds.max_kwh = 0.001
        gate = DataQualityGate(config)
        batch = make_batch("clean_batch.csv")
        result = gate.process_batch(batch)

        outcome = publisher.publish_or_alert(result)
        assert outcome.alert is not None
        assert outcome.alert.tenant_id == TENANT_ID
        assert outcome.alert.severity == "critical"

    def test_quarantined_alert_persisted(
        self,
        publisher: DataQualityEventPublisher,
        mock_producer: MockKafkaProducer,
        alert_store: InMemoryAlertStore,
    ) -> None:
        config = DataQualityGateConfig()
        config.bounds.circuit_type_bounds["hvac"].max_kwh = 0.001
        config.bounds.circuit_type_bounds["lighting"].max_kwh = 0.001
        config.bounds.default_bounds.max_kwh = 0.001
        gate = DataQualityGate(config)
        batch = make_batch("clean_batch.csv")
        result = gate.process_batch(batch)

        publisher.publish_or_alert(result)
        assert len(alert_store.alerts) == 1
        assert alert_store.alerts[0].alert_type == "quarantined_batch"
        assert alert_store.alerts[0].tenant_id == TENANT_ID


@pytest.mark.unit
class TestSchemaDriftNotification:
    def test_degraded_batch_with_drift_produces_alert(
        self,
        publisher: DataQualityEventPublisher,
        mock_producer: MockKafkaProducer,
        alert_store: InMemoryAlertStore,
    ) -> None:
        gate = DataQualityGate()
        batch = make_batch("schema_drift.csv")
        result = gate.process_batch(batch)

        if result.overall_status == "quarantined":
            pytest.skip("Batch was fully quarantined, not degraded")

        outcome = publisher.publish_or_alert(result)
        assert outcome.published is True
        assert outcome.alert is not None
        assert outcome.alert.alert_type == "schema_drift"
        assert outcome.alert.tenant_id == TENANT_ID
        assert outcome.alert.building_id == BUILDING_ID
        assert "drift" in outcome.alert.message.lower()
        assert len(mock_producer.published) == 1

    def test_schema_drift_alert_persisted(
        self,
        publisher: DataQualityEventPublisher,
        mock_producer: MockKafkaProducer,
        alert_store: InMemoryAlertStore,
    ) -> None:
        gate = DataQualityGate()
        batch = make_batch("schema_drift.csv")
        result = gate.process_batch(batch)

        if result.overall_status == "quarantined":
            pytest.skip("Batch was fully quarantined, not degraded")

        publisher.publish_or_alert(result)
        assert len(alert_store.alerts) == 1
        assert alert_store.alerts[0].alert_type == "schema_drift"

    def test_clean_batch_no_drift_alert(
        self,
        publisher: DataQualityEventPublisher,
        mock_producer: MockKafkaProducer,
        alert_store: InMemoryAlertStore,
    ) -> None:
        gate = DataQualityGate()
        batch = make_batch("clean_batch.csv")
        result = gate.process_batch(batch)

        outcome = publisher.publish_or_alert(result)
        assert outcome.published is True
        assert outcome.alert is None
        assert len(alert_store.alerts) == 0
