"""ENG-2c-wiring — lightweight Data Quality Gate verification (revised per
approval: the Gate stays in AnalysisPipelineWorkflow rather than being
removed, but as a check against already-persisted data, not a re-run of
DataQualityGate.process_batch() -- that method requires the raw,
pre-normalization batch (RawIngestionBatch.raw_rows, circuit_map), which
does not exist once ingestion has completed and cannot be reconstructed
from normalized_readings.

TRD v2.0 3.1's own rule -- "a quarantined-only batch does not trigger
downstream analysis and instead raises a data-quality alert to the
tenant" -- is what this repository lets the retained
data_quality_gate_activity re-check against the persisted record, using
the same async-SQLAlchemy-session, tenant-scoped-caller pattern as
services/calibration/repository.py and services/drift_detection/repository.py.
"""

from __future__ import annotations

import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.ingestion.models import BatchQualityResult, CircuitInfo, NormalizedReading


class DataQualityVerificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_status_counts(
        self,
        building_id: UUID,
        window_start: datetime.datetime,
        window_end: datetime.datetime,
    ) -> dict[str, int]:
        """Return {data_quality_status: count} for readings in the window.

        Missing statuses are simply absent from the returned dict --
        callers should use .get(status, 0).
        """
        stmt = text(
            """
            SELECT nr.data_quality_status, COUNT(*) AS n
            FROM normalized_readings nr
            JOIN submeter_circuits sc ON nr.circuit_id = sc.circuit_id
            WHERE sc.building_id = :building_id
              AND nr.ts >= :window_start
              AND nr.ts <= :window_end
            GROUP BY nr.data_quality_status
            """
        )
        result = await self._session.execute(
            stmt,
            {
                "building_id": str(building_id),
                "window_start": window_start,
                "window_end": window_end,
            },
        )
        return {row.data_quality_status: row.n for row in result.fetchall()}


# ---------------------------------------------------------------------------
# ENG-5b addition: the Ingestion API's write path. Nothing before ENG-5
# persisted a RawIngestionBatch's circuits/readings to the database at
# all -- DataQualityGate.process_batch() has always been callable but
# never actually wired to storage (only exercised directly in tests).
# submeter_circuits has no external-meter-ID column, so circuits are
# resolved/auto-provisioned by (building_id, label) -- label being exactly
# the free-text field the schema already carries for this purpose.
# ---------------------------------------------------------------------------


class IngestionWriteRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_or_create_circuits(
        self,
        tenant_id: UUID,
        building_id: UUID,
        meter_ids_and_types: dict[str, str],
    ) -> dict[str, CircuitInfo]:
        if not meter_ids_and_types:
            return {}

        existing_stmt = text(
            """
            SELECT circuit_id, circuit_type, label FROM submeter_circuits
            WHERE building_id = :building_id AND label = ANY(:labels)
            """
        )
        result = await self._session.execute(
            existing_stmt,
            {"building_id": str(building_id), "labels": list(meter_ids_and_types.keys())},
        )
        circuit_map: dict[str, CircuitInfo] = {
            row.label: CircuitInfo(circuit_id=row.circuit_id, circuit_type=row.circuit_type)
            for row in result.fetchall()
        }

        missing = {
            meter_id: circuit_type
            for meter_id, circuit_type in meter_ids_and_types.items()
            if meter_id not in circuit_map
        }
        if missing:
            insert_stmt = text(
                """
                INSERT INTO submeter_circuits (tenant_id, building_id, circuit_type, label)
                VALUES (:tenant_id, :building_id, :circuit_type, :label)
                RETURNING circuit_id, circuit_type, label
                """
            )
            for meter_id, circuit_type in missing.items():
                result = await self._session.execute(
                    insert_stmt,
                    {
                        "tenant_id": str(tenant_id),
                        "building_id": str(building_id),
                        "circuit_type": circuit_type,
                        "label": meter_id,
                    },
                )
                row = result.fetchone()
                assert row is not None
                circuit_map[row.label] = CircuitInfo(
                    circuit_id=row.circuit_id, circuit_type=row.circuit_type
                )

        return circuit_map

    async def save_readings(self, readings: list[NormalizedReading]) -> None:
        if not readings:
            return
        stmt = text(
            """
            INSERT INTO normalized_readings
                (tenant_id, circuit_id, ts, kwh, data_quality_status, schema_version)
            VALUES (:tenant_id, :circuit_id, :ts, :kwh, :data_quality_status, :schema_version)
            ON CONFLICT (tenant_id, circuit_id, ts) DO UPDATE SET
                kwh = EXCLUDED.kwh,
                data_quality_status = EXCLUDED.data_quality_status
            """
        )
        for reading in readings:
            await self._session.execute(
                stmt,
                {
                    "tenant_id": str(reading.tenant_id),
                    "circuit_id": str(reading.circuit_id),
                    "ts": reading.ts,
                    "kwh": reading.kwh,
                    "data_quality_status": reading.data_quality_status,
                    "schema_version": reading.schema_version,
                },
            )

    async def create_batch_record(
        self,
        tenant_id: UUID,
        building_id: UUID,
        result: BatchQualityResult,
    ) -> UUID:
        stmt = text(
            """
            INSERT INTO ingestion_batches (
                tenant_id, building_id, status, total_rows, pass_count,
                degraded_count, quarantined_count, ingestion_source
            ) VALUES (
                :tenant_id, :building_id, :status, :total_rows, :pass_count,
                :degraded_count, :quarantined_count, :ingestion_source
            )
            RETURNING batch_id
            """
        )
        result_row = await self._session.execute(
            stmt,
            {
                "tenant_id": str(tenant_id),
                "building_id": str(building_id),
                "status": result.overall_status,
                "total_rows": result.total_rows,
                "pass_count": result.pass_count,
                "degraded_count": result.degraded_count,
                "quarantined_count": result.quarantined_count,
                "ingestion_source": result.ingestion_source,
            },
        )
        row = result_row.fetchone()
        assert row is not None
        return cast(UUID, row.batch_id)

    async def get_batch(self, tenant_id: UUID, batch_id: UUID) -> dict[str, Any] | None:
        stmt = text(
            """
            SELECT batch_id, building_id, status, total_rows, pass_count,
                   degraded_count, quarantined_count, ingestion_source, created_at
            FROM ingestion_batches
            WHERE tenant_id = :tenant_id AND batch_id = :batch_id
            """
        )
        result = await self._session.execute(
            stmt, {"tenant_id": str(tenant_id), "batch_id": str(batch_id)}
        )
        row = result.fetchone()
        if row is None:
            return None
        return {
            "batch_id": row.batch_id,
            "building_id": row.building_id,
            "status": row.status,
            "total_rows": row.total_rows,
            "pass_count": row.pass_count,
            "degraded_count": row.degraded_count,
            "quarantined_count": row.quarantined_count,
            "ingestion_source": row.ingestion_source,
            "created_at": row.created_at,
        }


class IngestionWebhookRepository:
    """Smart-meter API webhook registration (TRD v2.0 §7.1) -- the inbound
    counterpart to apps.api.webhooks' outbound delivery. register() runs
    inside an authenticated, tenant-scoped request; get_by_id() is the
    pre-auth lookup the receiver endpoint uses (ingestion_webhooks carries
    no RLS policy -- see migration 0008's docstring).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def register(
        self, tenant_id: UUID, building_id: UUID, provider: str, receiver_secret_hash: str
    ) -> UUID:
        stmt = text(
            """
            INSERT INTO ingestion_webhooks (tenant_id, building_id, provider, receiver_secret_hash)
            VALUES (:tenant_id, :building_id, :provider, :receiver_secret_hash)
            RETURNING webhook_id
            """
        )
        result = await self._session.execute(
            stmt,
            {
                "tenant_id": str(tenant_id),
                "building_id": str(building_id),
                "provider": provider,
                "receiver_secret_hash": receiver_secret_hash,
            },
        )
        row = result.fetchone()
        assert row is not None
        return cast(UUID, row.webhook_id)

    async def get_by_id(self, webhook_id: UUID) -> dict[str, Any] | None:
        stmt = text(
            """
            SELECT webhook_id, tenant_id, building_id, provider, receiver_secret_hash, active
            FROM ingestion_webhooks
            WHERE webhook_id = :webhook_id
            """
        )
        result = await self._session.execute(stmt, {"webhook_id": str(webhook_id)})
        row = result.fetchone()
        if row is None:
            return None
        return {
            "webhook_id": row.webhook_id,
            "tenant_id": row.tenant_id,
            "building_id": row.building_id,
            "provider": row.provider,
            "receiver_secret_hash": row.receiver_secret_hash,
            "active": row.active,
        }
