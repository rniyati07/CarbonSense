"""ENG-5b/5d — Ingestion API (TRD v2.0 §7.1): CSV upload, smart-meter API
webhook registration, ingestion batch status.

The API publishes the resulting `building.data.arrived` event only -- it
never calls Client.start_workflow() directly. That decoupling
(orchestration/events/kafka/analysis_trigger.py's consumer starts
AnalysisPipelineWorkflow) is Phase 0's prerequisite work; this router must
not bypass it, per the explicit constraint in the ENG-5 spec.

CSV upload and the smart-meter push receiver both funnel through
services.ingestion.orchestrator.ingest_raw_rows() -- one code path through
DataQualityGate, not two, and one this router does not itself implement
(no business logic in apps/api).

The push receiver (POST /v1/ingestion/webhooks/{webhook_id}/push) is the
one endpoint in this API that is deliberately *not* behind JWT auth -- a
smart-meter provider has no CarbonSense OAuth2 client, only the receiver
secret issued at registration time. It looks up tenant/building from the
webhook_id itself (ingestion_webhooks carries no RLS -- see migration
0008), verifies X-Receiver-Secret, then opens its own explicit
tenant_scope() for the actual write, matching the same
factory()+tenant_scope() pattern used everywhere a request isn't the
source of the tenant context.
"""

from __future__ import annotations

import csv
import io
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import (
    get_event_publisher,
    get_tenant_scoped_session,
    get_validated_tenant_id,
)
from apps.api.idempotency import get_cached_response, store_response
from orchestration.events.kafka.producer import EventPublisher
from services.ingestion.orchestrator import ingest_raw_rows
from services.ingestion.repository import IngestionWebhookRepository, IngestionWriteRepository
from shared.auth.secrets import generate_client_secret, hash_client_secret, verify_client_secret
from shared.auth.tenant_context import tenant_scope
from shared.database import get_session_factory

router = APIRouter(prefix="/v1/ingestion", tags=["ingestion"])

_CSV_ENDPOINT = "POST /v1/ingestion/csv"
_RECEIVER_AUTH_FAILED_DETAIL = "Invalid webhook_id or X-Receiver-Secret"


class BatchAcceptedResponse(BaseModel):
    batch_id: UUID
    status: str
    poll_url: str


class BatchStatusResponse(BaseModel):
    batch_id: UUID
    building_id: UUID
    status: str
    total_rows: int
    pass_count: int
    degraded_count: int
    quarantined_count: int
    ingestion_source: str | None


class WebhookRegisterRequest(BaseModel):
    building_id: UUID
    provider: str


class WebhookRegisterResponse(BaseModel):
    webhook_id: UUID
    receiver_url: str
    receiver_secret: str


class WebhookPushReading(BaseModel):
    meter_id: str
    timestamp: str
    kwh: float | None = None
    circuit_type: str | None = None


class WebhookPushRequest(BaseModel):
    readings: list[WebhookPushReading]


@router.post("/csv", response_model=BatchAcceptedResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_csv(
    building_id: UUID,
    file: UploadFile = File(...),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    tenant_id: UUID = Depends(get_validated_tenant_id),
    session: AsyncSession = Depends(get_tenant_scoped_session),
    event_publisher: EventPublisher = Depends(get_event_publisher),
) -> BatchAcceptedResponse:
    if idempotency_key is not None:
        cached = await get_cached_response(session, tenant_id, idempotency_key, _CSV_ENDPOINT)
        if cached is not None:
            _, cached_body = cached
            return BatchAcceptedResponse(**cached_body)

    raw_bytes = await file.read()
    try:
        text_content = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="CSV file is not valid UTF-8"
        ) from exc

    raw_rows: list[dict[str, Any]] = list(csv.DictReader(io.StringIO(text_content)))
    if not raw_rows:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CSV file has no rows")

    batch_id = await ingest_raw_rows(
        session, tenant_id, building_id, raw_rows, "csv_upload", event_publisher
    )
    response = BatchAcceptedResponse(
        batch_id=batch_id, status="processing", poll_url=f"/v1/ingestion/batches/{batch_id}"
    )

    if idempotency_key is not None:
        await store_response(
            session,
            tenant_id,
            idempotency_key,
            _CSV_ENDPOINT,
            status.HTTP_202_ACCEPTED,
            response.model_dump(mode="json"),
        )

    return response


@router.get("/batches/{batch_id}", response_model=BatchStatusResponse)
async def get_batch_status(
    batch_id: UUID,
    tenant_id: UUID = Depends(get_validated_tenant_id),
    session: AsyncSession = Depends(get_tenant_scoped_session),
) -> BatchStatusResponse:
    batch = await IngestionWriteRepository(session).get_batch(tenant_id, batch_id)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Ingestion batch not found"
        )
    return BatchStatusResponse(**batch)


@router.post("/webhooks", response_model=WebhookRegisterResponse)
async def register_smart_meter_webhook(
    body: WebhookRegisterRequest,
    tenant_id: UUID = Depends(get_validated_tenant_id),
    session: AsyncSession = Depends(get_tenant_scoped_session),
) -> WebhookRegisterResponse:
    """TRD v2.0 §7.1: smart-meter API webhook registration. Returns a
    receiver URL + secret the caller configures with their smart-meter
    provider; provider-specific auth/formats are a BD decision (Appendix
    B, OQ-4) -- this endpoint owns only the generic receiver credential."""
    plaintext_secret = generate_client_secret()
    secret_hash = hash_client_secret(plaintext_secret)
    webhook_id = await IngestionWebhookRepository(session).register(
        tenant_id=tenant_id,
        building_id=body.building_id,
        provider=body.provider,
        receiver_secret_hash=secret_hash,
    )
    return WebhookRegisterResponse(
        webhook_id=webhook_id,
        receiver_url=f"/v1/ingestion/webhooks/{webhook_id}/push",
        receiver_secret=plaintext_secret,
    )


@router.post("/webhooks/{webhook_id}/push", status_code=status.HTTP_202_ACCEPTED)
async def push_smart_meter_readings(
    webhook_id: UUID,
    body: WebhookPushRequest,
    x_receiver_secret: str = Header(..., alias="X-Receiver-Secret"),
    event_publisher: EventPublisher = Depends(get_event_publisher),
) -> BatchAcceptedResponse:
    factory = get_session_factory()

    async with factory() as lookup_session:
        record = await IngestionWebhookRepository(lookup_session).get_by_id(webhook_id)

    if (
        record is None
        or not record["active"]
        or not verify_client_secret(x_receiver_secret, record["receiver_secret_hash"])
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=_RECEIVER_AUTH_FAILED_DETAIL
        )

    tenant_id: UUID = record["tenant_id"]
    building_id: UUID = record["building_id"]
    raw_rows: list[dict[str, Any]] = [
        {
            "meter_id": r.meter_id,
            "timestamp": r.timestamp,
            "kwh": r.kwh,
            "circuit_type": r.circuit_type,
        }
        for r in body.readings
    ]

    async with factory() as session, tenant_scope(session, tenant_id):
        batch_id = await ingest_raw_rows(
            session, tenant_id, building_id, raw_rows, "smart_meter_api", event_publisher
        )
        await session.commit()

    return BatchAcceptedResponse(
        batch_id=batch_id, status="processing", poll_url=f"/v1/ingestion/batches/{batch_id}"
    )
