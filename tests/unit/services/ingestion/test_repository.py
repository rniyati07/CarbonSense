from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from services.ingestion.repository import DataQualityVerificationRepository


def _mock_session_with_rows(rows: list[tuple[str, int]]) -> AsyncMock:
    """Build an AsyncSession mock whose execute() returns fetchall()-able
    rows with .data_quality_status / .n attributes, matching how
    DataQualityVerificationRepository reads them."""
    result = MagicMock()
    row_mocks = []
    for status, n in rows:
        row = MagicMock()
        row.data_quality_status = status
        row.n = n
        row_mocks.append(row)
    result.fetchall.return_value = row_mocks

    session = AsyncMock()
    session.execute.return_value = result
    return session


class TestDataQualityVerificationRepository:
    @pytest.mark.asyncio
    async def test_get_status_counts_returns_mapping(self) -> None:
        session = _mock_session_with_rows([("pass", 100), ("degraded", 5), ("quarantined", 2)])
        repo = DataQualityVerificationRepository(session)

        counts = await repo.get_status_counts(
            uuid4(),
            datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
            datetime.datetime(2026, 1, 31, tzinfo=datetime.UTC),
        )

        assert counts == {"pass": 100, "degraded": 5, "quarantined": 2}
        session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_status_counts_missing_statuses_absent(self) -> None:
        """Only 'pass' rows exist -- degraded/quarantined must be absent,
        not zero-filled, per the method's own documented .get(status, 0)
        contract."""
        session = _mock_session_with_rows([("pass", 10)])
        repo = DataQualityVerificationRepository(session)

        counts = await repo.get_status_counts(
            uuid4(),
            datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
            datetime.datetime(2026, 1, 31, tzinfo=datetime.UTC),
        )

        assert counts == {"pass": 10}
        assert counts.get("degraded", 0) == 0
        assert counts.get("quarantined", 0) == 0

    @pytest.mark.asyncio
    async def test_get_status_counts_empty_window_returns_empty_dict(self) -> None:
        session = _mock_session_with_rows([])
        repo = DataQualityVerificationRepository(session)

        counts = await repo.get_status_counts(
            uuid4(),
            datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
            datetime.datetime(2026, 1, 31, tzinfo=datetime.UTC),
        )

        assert counts == {}

    @pytest.mark.asyncio
    async def test_query_scoped_to_building_and_window(self) -> None:
        """The query params passed to execute() must carry building_id and
        the window bounds -- a regression guard against accidentally
        dropping the WHERE-clause scoping during a future edit."""
        session = _mock_session_with_rows([])
        repo = DataQualityVerificationRepository(session)
        building_id = uuid4()
        start = datetime.datetime(2026, 2, 1, tzinfo=datetime.UTC)
        end = datetime.datetime(2026, 2, 28, tzinfo=datetime.UTC)

        await repo.get_status_counts(building_id, start, end)

        params = session.execute.call_args.args[1]
        assert params["building_id"] == str(building_id)
        assert params["window_start"] == start
        assert params["window_end"] == end
