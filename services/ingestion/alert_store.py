"""Persistence layer for data quality alerts.

Writes ``DataQualityAlertPayload`` into the ``data_quality_alerts`` table
created in migration 0004.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from services.ingestion.models import DataQualityAlertPayload


class AlertStore(Protocol):
    def persist(self, alert: DataQualityAlertPayload) -> None: ...


class DatabaseAlertStore:
    """Writes alerts to the ``data_quality_alerts`` table."""

    def __init__(self, get_connection: Any) -> None:
        self._get_connection = get_connection

    def persist(self, alert: DataQualityAlertPayload) -> None:
        conn = self._get_connection()
        try:
            conn.execute(
                "INSERT INTO data_quality_alerts "
                "(tenant_id, building_id, alert_type, severity, message, metadata) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    str(alert.tenant_id),
                    str(alert.building_id),
                    alert.alert_type,
                    alert.severity,
                    alert.message,
                    json.dumps(
                        {k: v for k, v in alert.metadata.items() if v is not None}
                    ),
                ),
            )
            conn.commit()
        finally:
            conn.close()


class InMemoryAlertStore:
    """In-memory alert store for testing."""

    def __init__(self) -> None:
        self.alerts: list[DataQualityAlertPayload] = []

    def persist(self, alert: DataQualityAlertPayload) -> None:
        self.alerts.append(alert)
