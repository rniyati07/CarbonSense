from __future__ import annotations

import datetime
import uuid
from typing import TYPE_CHECKING

from orchestration.events.kafka.producer import EventPublisher
from orchestration.events.kafka.schemas.data_arrived import BuildingDataArrivedEvent
from shared.config.kafka import KafkaSettings

from services.ingestion.models import (
    BatchQualityResult,
    DataQualityAlertPayload,
    PublishOutcome,
)

if TYPE_CHECKING:
    from services.ingestion.alert_store import AlertStore


class DataQualityEventPublisher:
    def __init__(
        self,
        producer: EventPublisher,
        settings: KafkaSettings | None = None,
        alert_store: AlertStore | None = None,
    ) -> None:
        self._producer = producer
        self._settings = settings or KafkaSettings()
        self._alert_store = alert_store

    def _persist_alert(self, alert: DataQualityAlertPayload) -> None:
        if self._alert_store is not None:
            self._alert_store.persist(alert)

    def _build_schema_drift_alert(
        self,
        result: BatchQualityResult,
    ) -> DataQualityAlertPayload | None:
        drift_issues = [
            i for i in result.quality_issues if i.issue_type == "schema_drift"
        ]
        if not drift_issues:
            return None

        descriptions = "; ".join(i.description for i in drift_issues)
        return DataQualityAlertPayload(
            tenant_id=result.tenant_id,
            building_id=result.building_id,
            alert_type="schema_drift",
            severity="warning",
            message=(
                f"Schema drift detected in ingestion batch: {descriptions}. "
                f"Data accepted as degraded — review source schema."
            ),
            metadata={
                "drift_count": len(drift_issues),
                "data_quality_status": result.overall_status,
            },
        )

    def publish_or_alert(
        self,
        result: BatchQualityResult,
    ) -> PublishOutcome:
        if result.overall_status in ("pass", "degraded"):
            event = BuildingDataArrivedEvent(
                event_id=uuid.uuid4(),
                tenant_id=result.tenant_id,
                building_id=result.building_id,
                correlation_id=uuid.uuid4(),
                timestamp=datetime.datetime.now(datetime.timezone.utc),
                event_type="building.data.arrived",
                data_quality_status=result.overall_status,
                batch_row_count=result.total_rows,
                ingestion_source=result.ingestion_source,
            )
            self._producer.publish(self._settings.topic_data_arrived, event)

            drift_alert = self._build_schema_drift_alert(result)
            if drift_alert is not None:
                self._persist_alert(drift_alert)

            return PublishOutcome(published=True, alert=drift_alert)

        alert = DataQualityAlertPayload(
            tenant_id=result.tenant_id,
            building_id=result.building_id,
            alert_type="quarantined_batch",
            severity="critical",
            message=(
                f"Entire batch quarantined: {result.quarantined_count} rows. "
                f"No downstream analysis triggered. "
                f"Issues: {len(result.quality_issues)}"
            ),
            metadata={
                "total_rows": result.total_rows,
                "quarantined_count": result.quarantined_count,
                "issue_types": ", ".join(
                    sorted({i.issue_type for i in result.quality_issues})
                ),
            },
        )
        self._persist_alert(alert)
        return PublishOutcome(published=False, alert=alert)
