from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.feedback.repository import FeedbackRepository, FindingForFeedback


def _mock_session_with_result(rows=None, one_row=None) -> AsyncMock:
    session = AsyncMock()
    result = AsyncMock()
    result.fetchall = lambda: rows or []
    result.fetchone = lambda: one_row
    result.scalar = lambda: one_row
    session.execute.return_value = result
    return session


class TestGetFindingForFeedback:
    @pytest.mark.asyncio
    async def test_returns_none_when_finding_missing(self) -> None:
        session = _mock_session_with_result(one_row=None)
        repo = FeedbackRepository(session)
        result = await repo.get_finding_for_feedback(uuid.uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_maps_row_with_dict_bundle(self) -> None:
        building_id = uuid.uuid4()
        row = SimpleNamespace(building_id=building_id, explainability_bundle={"top_features": []})
        session = _mock_session_with_result(one_row=row)
        repo = FeedbackRepository(session)
        result = await repo.get_finding_for_feedback(uuid.uuid4())
        assert isinstance(result, FindingForFeedback)
        assert result.building_id == building_id
        assert result.explainability_bundle == {"top_features": []}

    @pytest.mark.asyncio
    async def test_parses_bundle_stored_as_json_string(self) -> None:
        row = SimpleNamespace(
            building_id=uuid.uuid4(), explainability_bundle='{"top_features": []}'
        )
        session = _mock_session_with_result(one_row=row)
        repo = FeedbackRepository(session)
        result = await repo.get_finding_for_feedback(uuid.uuid4())
        assert result.explainability_bundle == {"top_features": []}


class TestSaveFeedbackLabel:
    @pytest.mark.asyncio
    async def test_issues_insert_with_correct_params(self) -> None:
        session = AsyncMock()
        repo = FeedbackRepository(session)
        feedback_id, tenant_id, finding_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

        await repo.save_feedback_label(
            feedback_id=feedback_id,
            tenant_id=tenant_id,
            finding_id=finding_id,
            action="confirmed",
            actor="test_user",
            created_at="2026-01-01T00:00:00Z",
        )

        session.execute.assert_awaited_once()
        params = session.execute.call_args.args[1]
        assert params["feedback_id"] == str(feedback_id)
        assert params["tenant_id"] == str(tenant_id)
        assert params["finding_id"] == str(finding_id)
        assert params["action"] == "confirmed"
        assert params["actor"] == "test_user"


class TestUpdateFindingStatus:
    @pytest.mark.asyncio
    async def test_issues_update_with_status(self) -> None:
        session = AsyncMock()
        repo = FeedbackRepository(session)
        finding_id = uuid.uuid4()

        await repo.update_finding_status(finding_id, "dismissed")

        session.execute.assert_awaited_once()
        params = session.execute.call_args.args[1]
        assert params["status"] == "dismissed"
        assert params["fid"] == str(finding_id)


class TestCountFeedbackForBuilding:
    @pytest.mark.asyncio
    async def test_returns_scalar_count(self) -> None:
        session = _mock_session_with_result(one_row=5)
        repo = FeedbackRepository(session)
        result = await repo.count_feedback_for_building(uuid.uuid4(), uuid.uuid4())
        assert result == 5

    @pytest.mark.asyncio
    async def test_returns_zero_when_scalar_is_none(self) -> None:
        session = _mock_session_with_result(one_row=None)
        repo = FeedbackRepository(session)
        result = await repo.count_feedback_for_building(uuid.uuid4(), uuid.uuid4())
        assert result == 0
