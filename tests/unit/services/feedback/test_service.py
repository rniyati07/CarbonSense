from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from services.feedback.repository import FindingForFeedback
from services.feedback.service import (
    RETRAINING_THRESHOLD,
    FeedbackService,
    FindingNotFoundError,
    InvalidFeedbackActionError,
    MissingExplainabilityBundleError,
)

from .conftest import MockEventPublisher


@pytest.mark.unit
class TestFeedbackService:
    @pytest.mark.asyncio
    async def test_rejects_invalid_action(
        self,
        tenant_id: uuid.UUID,
        finding_id: uuid.UUID,
        mock_repository: AsyncMock,
    ) -> None:
        service = FeedbackService(repository=mock_repository)

        with pytest.raises(InvalidFeedbackActionError):
            await service.record_feedback(
                tenant_id=tenant_id, finding_id=finding_id, action="maybe", actor="test_user"
            )

        mock_repository.get_finding_for_feedback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rejects_empty_bundle(
        self,
        tenant_id: uuid.UUID,
        finding_id: uuid.UUID,
        mock_repository: AsyncMock,
    ) -> None:
        mock_repository.get_finding_for_feedback.return_value = FindingForFeedback(
            building_id=uuid.uuid4(), explainability_bundle={}
        )
        service = FeedbackService(repository=mock_repository)

        with pytest.raises(MissingExplainabilityBundleError, match="no explainability bundle"):
            await service.record_feedback(
                tenant_id=tenant_id, finding_id=finding_id, action="confirmed", actor="test_user"
            )

        mock_repository.save_feedback_label.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rejects_null_bundle(
        self,
        tenant_id: uuid.UUID,
        finding_id: uuid.UUID,
        mock_repository: AsyncMock,
    ) -> None:
        mock_repository.get_finding_for_feedback.return_value = FindingForFeedback(
            building_id=uuid.uuid4(), explainability_bundle=None
        )
        service = FeedbackService(repository=mock_repository)

        with pytest.raises(MissingExplainabilityBundleError):
            await service.record_feedback(
                tenant_id=tenant_id, finding_id=finding_id, action="confirmed", actor="test_user"
            )

    @pytest.mark.asyncio
    async def test_finding_not_found(
        self,
        tenant_id: uuid.UUID,
        finding_id: uuid.UUID,
        mock_repository: AsyncMock,
    ) -> None:
        mock_repository.get_finding_for_feedback.return_value = None
        service = FeedbackService(repository=mock_repository)

        with pytest.raises(FindingNotFoundError, match="not found or is not visible"):
            await service.record_feedback(
                tenant_id=tenant_id, finding_id=finding_id, action="confirmed", actor="test_user"
            )

    @pytest.mark.asyncio
    async def test_success_no_retrain(
        self,
        tenant_id: uuid.UUID,
        finding_id: uuid.UUID,
        mock_repository: AsyncMock,
        mock_event_publisher: MockEventPublisher,
    ) -> None:
        building_id = uuid.uuid4()
        mock_repository.get_finding_for_feedback.return_value = FindingForFeedback(
            building_id=building_id, explainability_bundle={"top_features": []}
        )
        mock_repository.count_feedback_for_building.return_value = 3

        service = FeedbackService(repository=mock_repository, event_publisher=mock_event_publisher)
        await service.record_feedback(
            tenant_id=tenant_id, finding_id=finding_id, action="confirmed", actor="test_user"
        )

        mock_repository.save_feedback_label.assert_awaited_once()
        save_kwargs = mock_repository.save_feedback_label.call_args.kwargs
        assert save_kwargs["tenant_id"] == tenant_id
        assert save_kwargs["finding_id"] == finding_id
        assert save_kwargs["action"] == "confirmed"
        assert save_kwargs["actor"] == "test_user"

        mock_repository.update_finding_status.assert_awaited_once_with(finding_id, "confirmed")
        assert mock_event_publisher.published_events == []

    @pytest.mark.asyncio
    async def test_retraining_eligibility_fires_exactly_at_threshold(
        self,
        tenant_id: uuid.UUID,
        finding_id: uuid.UUID,
        mock_repository: AsyncMock,
        mock_event_publisher: MockEventPublisher,
    ) -> None:
        building_id = uuid.uuid4()
        mock_repository.get_finding_for_feedback.return_value = FindingForFeedback(
            building_id=building_id, explainability_bundle={"top_features": []}
        )
        service = FeedbackService(repository=mock_repository, event_publisher=mock_event_publisher)

        # Below threshold: no event.
        mock_repository.count_feedback_for_building.return_value = RETRAINING_THRESHOLD - 1
        await service.record_feedback(
            tenant_id=tenant_id, finding_id=finding_id, action="confirmed", actor="test_user"
        )
        assert len(mock_event_publisher.published_events) == 0

        # Exactly at threshold: fires once.
        mock_repository.count_feedback_for_building.return_value = RETRAINING_THRESHOLD
        await service.record_feedback(
            tenant_id=tenant_id, finding_id=finding_id, action="confirmed", actor="test_user"
        )
        assert len(mock_event_publisher.published_events) == 1
        topic, event = mock_event_publisher.published_events[0]
        assert topic == "model.retraining.eligible"
        assert event.tenant_id == tenant_id
        assert event.building_id == building_id
        assert event.feedback_count == RETRAINING_THRESHOLD
        assert event.retraining_threshold == RETRAINING_THRESHOLD

        # Above threshold: does not fire again.
        mock_repository.count_feedback_for_building.return_value = RETRAINING_THRESHOLD + 1
        await service.record_feedback(
            tenant_id=tenant_id, finding_id=finding_id, action="confirmed", actor="test_user"
        )
        assert len(mock_event_publisher.published_events) == 1

    @pytest.mark.asyncio
    async def test_no_event_publisher_configured_does_not_raise(
        self,
        tenant_id: uuid.UUID,
        finding_id: uuid.UUID,
        mock_repository: AsyncMock,
    ) -> None:
        mock_repository.get_finding_for_feedback.return_value = FindingForFeedback(
            building_id=uuid.uuid4(), explainability_bundle={"top_features": []}
        )
        mock_repository.count_feedback_for_building.return_value = RETRAINING_THRESHOLD

        service = FeedbackService(repository=mock_repository)  # no event_publisher
        await service.record_feedback(
            tenant_id=tenant_id, finding_id=finding_id, action="dismissed", actor="test_user"
        )  # must not raise
