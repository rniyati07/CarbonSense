from __future__ import annotations

import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from models.evaluation.metrics import compute_false_positive_rate


def _mock_session_with_counts(rows: list) -> AsyncMock:
    session = AsyncMock()
    result = AsyncMock()
    result.fetchall = lambda: rows
    session.execute.return_value = result
    return session


@pytest.mark.unit
class TestComputeFalsePositiveRate:
    @pytest.mark.asyncio
    async def test_none_when_no_labeled_feedback(self) -> None:
        session = _mock_session_with_counts([])
        now = datetime.datetime.now(datetime.UTC)

        metrics = await compute_false_positive_rate(session, uuid4(), uuid4(), now, now)

        assert metrics.n_labeled == 0
        assert metrics.false_positive_rate is None

    @pytest.mark.asyncio
    async def test_computes_rate_from_confirmed_and_dismissed_counts(self) -> None:
        rows = [SimpleNamespace(action="confirmed", n=7), SimpleNamespace(action="dismissed", n=3)]
        session = _mock_session_with_counts(rows)
        now = datetime.datetime.now(datetime.UTC)

        metrics = await compute_false_positive_rate(session, uuid4(), uuid4(), now, now)

        assert metrics.n_confirmed == 7
        assert metrics.n_dismissed == 3
        assert metrics.n_labeled == 10
        assert metrics.false_positive_rate == pytest.approx(0.3)

    @pytest.mark.asyncio
    async def test_all_dismissed_gives_rate_of_one(self) -> None:
        rows = [SimpleNamespace(action="dismissed", n=5)]
        session = _mock_session_with_counts(rows)
        now = datetime.datetime.now(datetime.UTC)

        metrics = await compute_false_positive_rate(session, uuid4(), uuid4(), now, now)

        assert metrics.false_positive_rate == pytest.approx(1.0)
