from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from models.registry.audit import count_promotions, log_model_event


@pytest.mark.unit
class TestLogModelEvent:
    @pytest.mark.asyncio
    async def test_inserts_into_audit_log(self) -> None:
        session = AsyncMock()
        tenant_id = uuid4()

        await log_model_event(
            session, tenant_id=tenant_id, event_type="model.promoted", payload={"version": "1"}
        )

        session.execute.assert_awaited_once()
        params = session.execute.call_args.args[1]
        assert params["tenant_id"] == str(tenant_id)
        assert params["event_type"] == "model.promoted"
        assert '"version": "1"' in params["payload"]


@pytest.mark.unit
class TestCountPromotions:
    @pytest.mark.asyncio
    async def test_returns_zero_when_no_rows(self) -> None:
        session = AsyncMock()
        result = AsyncMock()
        result.fetchone = lambda: None
        session.execute.return_value = result

        count = await count_promotions(session, uuid4(), uuid4(), "isolation_forest")
        assert count == 0

    @pytest.mark.asyncio
    async def test_returns_count_from_row(self) -> None:
        session = AsyncMock()
        result = AsyncMock()
        result.fetchone = lambda: SimpleNamespace(n=3)
        session.execute.return_value = result

        count = await count_promotions(session, uuid4(), uuid4(), "isolation_forest")
        assert count == 3
