"""ENG-5d — Idempotency-Key support (TRD v2.0 §7.3): "Ingestion and
analysis-trigger endpoints accept an Idempotency-Key header so a retried
request... does not double-trigger a pipeline run." Keyed on
(tenant_id, idempotency_key, endpoint) per migration 0008 -- endpoint is
part of the key so the same client-chosen key value used against two
different endpoints can never collide.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def get_cached_response(
    session: AsyncSession, tenant_id: UUID, key: str, endpoint: str
) -> tuple[int, dict[str, Any]] | None:
    stmt = text(
        """
        SELECT response_status, response_body
        FROM idempotency_keys
        WHERE tenant_id = :tenant_id AND idempotency_key = :key AND endpoint = :endpoint
        """
    )
    result = await session.execute(
        stmt, {"tenant_id": str(tenant_id), "key": key, "endpoint": endpoint}
    )
    row = result.fetchone()
    if row is None:
        return None
    body = row.response_body
    if isinstance(body, str):
        body = json.loads(body)
    return row.response_status, body


async def store_response(
    session: AsyncSession,
    tenant_id: UUID,
    key: str,
    endpoint: str,
    status_code: int,
    body: dict[str, Any],
) -> None:
    stmt = text(
        """
        INSERT INTO idempotency_keys
            (tenant_id, idempotency_key, endpoint, response_status, response_body)
        VALUES (:tenant_id, :key, :endpoint, :status_code, :body)
        ON CONFLICT (tenant_id, idempotency_key, endpoint) DO NOTHING
        """
    )
    await session.execute(
        stmt,
        {
            "tenant_id": str(tenant_id),
            "key": key,
            "endpoint": endpoint,
            "status_code": status_code,
            "body": json.dumps(body),
        },
    )
