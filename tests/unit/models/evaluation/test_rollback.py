from __future__ import annotations

import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from models.evaluation.rollback import RollbackMonitor, RollbackSettings


def _session_with_label_counts(rows: list) -> AsyncMock:
    session = AsyncMock()
    result = AsyncMock()
    result.fetchall = lambda: rows
    session.execute.return_value = result
    return session


@pytest.mark.unit
class TestRollbackMonitor:
    @pytest.mark.asyncio
    async def test_no_rollback_when_too_few_labeled_samples(self) -> None:
        registry = MagicMock()
        monitor = RollbackMonitor(registry, RollbackSettings(min_sample_size=10))
        session = _session_with_label_counts([SimpleNamespace(action="dismissed", n=2)])
        now = datetime.datetime.now(datetime.UTC)

        decision = await monitor.check_and_rollback(
            session, uuid4(), uuid4(), "isolation_forest", now, now
        )

        assert decision.rolled_back is False
        assert "too few" in decision.reason.lower()
        registry.promote.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_rollback_when_fp_rate_within_ceiling(self) -> None:
        registry = MagicMock()
        monitor = RollbackMonitor(registry, RollbackSettings(max_fp_rate=0.5, min_sample_size=5))
        rows = [SimpleNamespace(action="confirmed", n=8), SimpleNamespace(action="dismissed", n=2)]
        session = _session_with_label_counts(rows)
        now = datetime.datetime.now(datetime.UTC)

        decision = await monitor.check_and_rollback(
            session, uuid4(), uuid4(), "isolation_forest", now, now
        )

        assert decision.rolled_back is False
        registry.promote.assert_not_called()

    @pytest.mark.asyncio
    async def test_rolls_back_when_fp_rate_exceeds_ceiling_and_prior_version_exists(self) -> None:
        registry = MagicMock()
        registry.get_previous_version.return_value = "1"
        registry.get_champion_version.return_value = "2"
        monitor = RollbackMonitor(registry, RollbackSettings(max_fp_rate=0.3, min_sample_size=5))
        rows = [SimpleNamespace(action="confirmed", n=2), SimpleNamespace(action="dismissed", n=8)]
        session = _session_with_label_counts(rows)
        now = datetime.datetime.now(datetime.UTC)

        decision = await monitor.check_and_rollback(
            session, uuid4(), uuid4(), "isolation_forest", now, now
        )

        assert decision.rolled_back is True
        assert decision.new_champion_version == "1"
        registry.promote.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_rollback_when_ceiling_exceeded_but_no_prior_version(self) -> None:
        registry = MagicMock()
        registry.get_previous_version.return_value = None
        monitor = RollbackMonitor(registry, RollbackSettings(max_fp_rate=0.3, min_sample_size=5))
        rows = [SimpleNamespace(action="dismissed", n=10)]
        session = _session_with_label_counts(rows)
        now = datetime.datetime.now(datetime.UTC)

        decision = await monitor.check_and_rollback(
            session, uuid4(), uuid4(), "isolation_forest", now, now
        )

        assert decision.rolled_back is False
        assert "no prior version" in decision.reason.lower()
        registry.promote.assert_not_called()
