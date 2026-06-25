"""ENG-3a integration test: full Data Quality Gate pipeline.

Tests the end-to-end flow:
  CSV → DataQualityGate → DataQualityEventPublisher → Kafka + alert persistence

Covers both happy-path (pass/degraded → publish) and quarantine path
(quarantined → no publish, alert persisted).

Does NOT require Docker or external services — uses in-process mocks for
Kafka and an InMemoryAlertStore for the data_quality_alerts table.
For a full Docker-based Kafka round-trip, see test_kafka_roundtrip.py.
"""

from __future__ import annotations

import pytest

from orchestration.events.kafka.schemas.base import BaseEvent
from services.ingestion.alert_store import InMemoryAlertStore
from services.ingestion.bounds_repository import InMemoryBoundsRepository
from services.ingestion.config import BoundsConfig, BoundsEntry, DataQualityGateConfig
from services.ingestion.event_publisher import DataQualityEventPublisher
from services.ingestion.models import CircuitInfo
from services.ingestion.quality_gate import DataQualityGate
from shared.config.kafka import KafkaSettings
from tests.unit.services.ingestion.conftest import (
    BUILDING_ID,
    HVAC_CIRCUIT_ID,
    LIGHT_CIRCUIT_ID,
    TENANT_ID,
    make_batch,
)


class RecordingKafkaProducer:
    """Records published events for assertion without a real broker."""

    def __init__(self) -> None:
        self.published: list[tuple[str, BaseEvent]] = []

    def publish(self, topic: str, event: BaseEvent) -> None:
        self.published.append((topic, event))

    def flush(self, timeout: float = 5.0) -> int:
        return 0


pytestmark = pytest.mark.integration


class TestCleanBatchEndToEnd:
    """CSV → Gate → pass → Kafka publish, no alerts."""

    def test_clean_csv_publishes_building_data_arrived(self) -> None:
        producer = RecordingKafkaProducer()
        alert_store = InMemoryAlertStore()
        publisher = DataQualityEventPublisher(
            producer=producer,
            settings=KafkaSettings(),
            alert_store=alert_store,
        )
        gate = DataQualityGate()

        batch = make_batch("clean_batch.csv")
        result = gate.process_batch(batch)

        assert result.overall_status == "pass"
        assert result.total_rows > 0
        for r in result.readings:
            assert r.schema_version == "normalized_reading_v1"
            assert r.data_quality_status == "pass"
            assert r.ts.tzinfo is not None

        outcome = publisher.publish_or_alert(result)

        assert outcome.published is True
        assert outcome.alert is None
        assert len(producer.published) == 1
        topic, event = producer.published[0]
        assert topic == "building.data.arrived"
        assert event.event_type == "building.data.arrived"
        assert event.tenant_id == TENANT_ID
        assert event.building_id == BUILDING_ID
        assert len(alert_store.alerts) == 0


class TestQuarantinedBatchEndToEnd:
    """CSV → Gate → quarantined → no Kafka, alert persisted."""

    def test_all_implausible_quarantines_and_persists_alert(self) -> None:
        producer = RecordingKafkaProducer()
        alert_store = InMemoryAlertStore()

        strict_bounds = InMemoryBoundsRepository(
            BoundsConfig(
                circuit_type_bounds={
                    "hvac": BoundsEntry(min_kwh=0.0, max_kwh=0.001),
                    "lighting": BoundsEntry(min_kwh=0.0, max_kwh=0.001),
                },
                default_bounds=BoundsEntry(min_kwh=0.0, max_kwh=0.001),
            )
        )

        publisher = DataQualityEventPublisher(
            producer=producer,
            settings=KafkaSettings(),
            alert_store=alert_store,
        )
        gate = DataQualityGate(bounds_repo=strict_bounds)

        batch = make_batch("clean_batch.csv")
        result = gate.process_batch(batch)

        assert result.overall_status == "quarantined"
        assert result.quarantined_count > 0

        outcome = publisher.publish_or_alert(result)

        assert outcome.published is False
        assert len(producer.published) == 0
        assert outcome.alert is not None
        assert outcome.alert.alert_type == "quarantined_batch"
        assert outcome.alert.tenant_id == TENANT_ID
        assert outcome.alert.building_id == BUILDING_ID
        assert outcome.alert.severity == "critical"

        assert len(alert_store.alerts) == 1
        persisted = alert_store.alerts[0]
        assert persisted.alert_type == "quarantined_batch"
        assert persisted.tenant_id == TENANT_ID


class TestSchemaDriftEndToEnd:
    """CSV with drifted schema → Gate → degraded → Kafka + drift alert persisted."""

    def test_schema_drift_publishes_and_persists_drift_alert(self) -> None:
        producer = RecordingKafkaProducer()
        alert_store = InMemoryAlertStore()
        publisher = DataQualityEventPublisher(
            producer=producer,
            settings=KafkaSettings(),
            alert_store=alert_store,
        )
        gate = DataQualityGate()

        batch = make_batch("schema_drift.csv")
        result = gate.process_batch(batch)

        if result.overall_status == "quarantined":
            pytest.skip("Batch was fully quarantined, not degraded")

        drift_issues = [
            i for i in result.quality_issues if i.issue_type == "schema_drift"
        ]
        assert len(drift_issues) > 0

        outcome = publisher.publish_or_alert(result)

        assert outcome.published is True
        assert len(producer.published) == 1

        assert outcome.alert is not None
        assert outcome.alert.alert_type == "schema_drift"
        assert outcome.alert.tenant_id == TENANT_ID
        assert "drift" in outcome.alert.message.lower()

        assert len(alert_store.alerts) == 1
        persisted = alert_store.alerts[0]
        assert persisted.alert_type == "schema_drift"
        assert persisted.tenant_id == TENANT_ID


class TestGapBeyondBoundEndToEnd:
    """CSV with large gap → Gate → degraded/quarantined rows → appropriate handling."""

    def test_gap_beyond_bound_handled_correctly(self) -> None:
        producer = RecordingKafkaProducer()
        alert_store = InMemoryAlertStore()
        publisher = DataQualityEventPublisher(
            producer=producer,
            settings=KafkaSettings(),
            alert_store=alert_store,
        )
        gate = DataQualityGate()

        batch = make_batch("gap_beyond_bound.csv")
        result = gate.process_batch(batch)

        gap_issues = [
            i for i in result.quality_issues if i.issue_type == "gap_beyond_bound"
        ]
        assert len(gap_issues) > 0
        assert result.quarantined_count > 0

        outcome = publisher.publish_or_alert(result)

        if result.overall_status == "quarantined":
            assert outcome.published is False
            assert len(alert_store.alerts) == 1
            assert alert_store.alerts[0].alert_type == "quarantined_batch"
        else:
            assert outcome.published is True
            assert len(producer.published) == 1


class TestSensorFaultEndToEnd:
    """CSV with stuck-at-value → Gate → detected fault → downstream handling."""

    def test_stuck_at_value_end_to_end(self) -> None:
        producer = RecordingKafkaProducer()
        alert_store = InMemoryAlertStore()
        publisher = DataQualityEventPublisher(
            producer=producer,
            settings=KafkaSettings(),
            alert_store=alert_store,
        )
        gate = DataQualityGate()

        batch = make_batch("stuck_at_value.csv")
        result = gate.process_batch(batch)

        stuck_issues = [
            i for i in result.quality_issues if i.issue_type == "stuck_at_value"
        ]
        assert len(stuck_issues) > 0
        assert result.overall_status in ("degraded", "quarantined")

        outcome = publisher.publish_or_alert(result)

        if result.overall_status == "quarantined":
            assert outcome.published is False
            assert len(alert_store.alerts) == 1
        else:
            assert outcome.published is True


class TestBoundsRepositoryIntegration:
    """Verify hot-reloadable bounds flow through the full pipeline."""

    def test_bounds_repo_overrides_config_defaults(self) -> None:
        producer = RecordingKafkaProducer()
        alert_store = InMemoryAlertStore()
        publisher = DataQualityEventPublisher(
            producer=producer,
            settings=KafkaSettings(),
            alert_store=alert_store,
        )

        repo = InMemoryBoundsRepository(
            BoundsConfig(
                circuit_type_bounds={
                    "hvac": BoundsEntry(min_kwh=0.0, max_kwh=10.0),
                    "lighting": BoundsEntry(min_kwh=0.0, max_kwh=10.0),
                },
                default_bounds=BoundsEntry(min_kwh=0.0, max_kwh=10.0),
            )
        )
        gate = DataQualityGate(bounds_repo=repo)

        batch = make_batch("clean_batch.csv")
        result = gate.process_batch(batch)

        implausible = [
            i for i in result.quality_issues if i.issue_type == "implausible_value"
        ]
        assert len(implausible) > 0

    def test_bounds_repo_hot_reload_mid_pipeline(self) -> None:
        repo = InMemoryBoundsRepository()
        gate = DataQualityGate(bounds_repo=repo)

        batch = make_batch("clean_batch.csv")
        result1 = gate.process_batch(batch)
        assert result1.overall_status == "pass"

        repo.set(
            BoundsConfig(
                circuit_type_bounds={
                    "hvac": BoundsEntry(min_kwh=0.0, max_kwh=0.001),
                    "lighting": BoundsEntry(min_kwh=0.0, max_kwh=0.001),
                },
                default_bounds=BoundsEntry(min_kwh=0.0, max_kwh=0.001),
            )
        )
        result2 = gate.process_batch(batch)
        assert result2.overall_status == "quarantined"
