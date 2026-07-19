"""ENG-5d — HMAC-signed webhook delivery (TRD v2.0 §7.3): "Callers either
poll poll_url or register a webhook (per-tenant configurable callback URL,
HMAC-signed payloads) for completion delivery." The signature is computed
over the payload's other fields and then embedded as the payload's own
"signature" field, matching TRD's literal example JSON -- also sent as an
X-CarbonSense-Signature header for callers that prefer to verify without
parsing the body first.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def sign_payload(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"hmac-sha256:{digest}"


async def _get_active_webhooks(
    session: AsyncSession, tenant_id: UUID, event_type: str
) -> list[tuple[UUID, str, str]]:
    stmt = text(
        """
        SELECT webhook_id, url, hmac_secret
        FROM webhook_registrations
        WHERE tenant_id = :tenant_id AND active = TRUE AND :event_type = ANY(event_types)
        """
    )
    result = await session.execute(stmt, {"tenant_id": str(tenant_id), "event_type": event_type})
    return [(row.webhook_id, row.url, row.hmac_secret) for row in result.fetchall()]


async def _deliver(url: str, secret: str, payload: dict[str, Any]) -> None:
    unsigned_body = json.dumps(payload, sort_keys=True, default=str).encode()
    signature = sign_payload(secret, unsigned_body)
    signed_payload = {**payload, "signature": signature}
    body = json.dumps(signed_payload, default=str).encode()
    headers = {"Content-Type": "application/json", "X-CarbonSense-Signature": signature}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, content=body, headers=headers)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.error("Webhook delivery to %s failed: %s", url, exc)


async def notify_webhooks(
    session: AsyncSession, tenant_id: UUID, event_type: str, payload: dict[str, Any]
) -> None:
    """Best-effort delivery: a failed webhook is logged, never raised --
    the poll_url remains the reliable path (§7.3: "Callers either poll... or
    register a webhook"), so delivery failure here must not fail the
    underlying job that already completed successfully.
    """
    webhooks = await _get_active_webhooks(session, tenant_id, event_type)
    for _webhook_id, url, secret in webhooks:
        await _deliver(url, secret, {**payload, "event": event_type})
