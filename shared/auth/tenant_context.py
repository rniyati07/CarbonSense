"""Tenant context management for RLS enforcement.

Sets app.current_tenant_id on each database connection so Postgres RLS
policies enforce tenant isolation at the storage layer. The tenant_id
comes from the validated JWT's tenant claim — never from a client-
supplied header alone (TRD v2.0 §7.2).

This module provides the database-layer primitive. The HTTP middleware
that extracts tenant_id from the token and calls set_tenant_context()
belongs to ENG-5 (API layer, not yet built).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession


async def set_tenant_context(session: AsyncSession, tenant_id: UUID) -> None:
    """Set the tenant context for the current database transaction.

    Uses SET LOCAL so the setting is scoped to the current transaction
    and cannot leak across pooled connections.
    """
    await session.execute(
        text("SET LOCAL app.current_tenant_id = :tenant_id"),
        {"tenant_id": str(tenant_id)},
    )


async def set_tenant_context_conn(conn: AsyncConnection, tenant_id: UUID) -> None:
    """Set tenant context on a raw connection (for non-ORM usage)."""
    await conn.execute(
        text("SET LOCAL app.current_tenant_id = :tenant_id"),
        {"tenant_id": str(tenant_id)},
    )


async def clear_tenant_context(session: AsyncSession) -> None:
    """Reset the tenant context. Primarily for testing."""
    await session.execute(text("RESET app.current_tenant_id"))


@asynccontextmanager
async def tenant_scope(session: AsyncSession, tenant_id: UUID) -> AsyncIterator[AsyncSession]:
    """Context manager that sets tenant context for a transaction block.

    Usage (in a request handler, once ENG-5 is built):

        async with tenant_scope(session, token.tenant_id) as scoped:
            result = await scoped.execute(select(Building))
    """
    await set_tenant_context(session, tenant_id)
    try:
        yield session
    finally:
        await clear_tenant_context(session)
