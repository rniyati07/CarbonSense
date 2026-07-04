from __future__ import annotations

import json
import uuid
import pytest

from services.feedback.service import RETRAINING_THRESHOLD, FeedbackService


@pytest.mark.unit
class TestFeedbackService:
    def test_record_feedback_checks_explainability_bundle_rejects_empty(
        self,
        tenant_id: uuid.UUID,
        finding_id: uuid.UUID,
        mock_connection: any,
    ) -> None:
        # Mock finding exists but explainability_bundle is empty dict
        mock_connection.cursor_obj.query_responses = {
            "FROM findings": [[(uuid.uuid4(), {})]],
        }

        def get_conn():
            return mock_connection

        service = FeedbackService(get_connection=get_conn)

        with pytest.raises(ValueError) as exc:
            service.record_feedback(
                tenant_id=tenant_id,
                finding_id=finding_id,
                action="confirmed",
                actor="test_user",
            )

        assert "has no explainability bundle" in str(exc.value)
        # Verify rollback occurred
        assert mock_connection.rolled_back is True
        # Verify we set RLS tenant ID context
        has_rls_set = any(
            "SET LOCAL app.current_tenant_id" in q[0] and str(tenant_id) in str(q[1])
            for q in mock_connection.executed_queries
        )
        assert has_rls_set is True

    def test_record_feedback_checks_explainability_bundle_rejects_null(
        self,
        tenant_id: uuid.UUID,
        finding_id: uuid.UUID,
        mock_connection: any,
    ) -> None:
        # Mock finding exists but explainability_bundle is None
        mock_connection.cursor_obj.query_responses = {
            "FROM findings": [[(uuid.uuid4(), None)]],
        }

        def get_conn():
            return mock_connection

        service = FeedbackService(get_connection=get_conn)

        with pytest.raises(ValueError) as exc:
            service.record_feedback(
                tenant_id=tenant_id,
                finding_id=finding_id,
                action="confirmed",
                actor="test_user",
            )

        assert "has no explainability bundle" in str(exc.value)
        assert mock_connection.rolled_back is True

    def test_record_feedback_not_found(
        self,
        tenant_id: uuid.UUID,
        finding_id: uuid.UUID,
        mock_connection: any,
    ) -> None:
        # Finding does not exist
        mock_connection.cursor_obj.query_responses = {
            "FROM findings": [[]],
        }

        def get_conn():
            return mock_connection

        service = FeedbackService(get_connection=get_conn)

        with pytest.raises(ValueError) as exc:
            service.record_feedback(
                tenant_id=tenant_id,
                finding_id=finding_id,
                action="confirmed",
                actor="test_user",
            )

        assert "not found or is not visible" in str(exc.value)
        assert mock_connection.rolled_back is True

    def test_record_feedback_success_no_retrain(
        self,
        tenant_id: uuid.UUID,
        finding_id: uuid.UUID,
        mock_connection: any,
        mock_event_publisher: any,
    ) -> None:
        # Mock finding with a valid explainability bundle
        building_id = uuid.uuid4()
        bundle_str = json.dumps({"finding_id": str(finding_id), "top_features": []})
        mock_connection.cursor_obj.query_responses = {
            "FROM findings": [[(building_id, bundle_str)]],
            "COUNT(*)": [[(3,)]],
        }

        def get_conn():
            return mock_connection

        service = FeedbackService(
            get_connection=get_conn,
            event_publisher=mock_event_publisher,
        )

        service.record_feedback(
            tenant_id=tenant_id,
            finding_id=finding_id,
            action="confirmed",
            actor="test_user",
        )

        assert mock_connection.committed is True
        assert len(mock_event_publisher.published_events) == 0

        # Check queries executed
        queries = [q[0] for q in mock_connection.executed_queries]

        assert any("INSERT INTO feedback_labels" in q for q in queries)
        assert any("UPDATE findings SET status" in q for q in queries)
        assert any("COUNT(*)" in q for q in queries)

    def test_retraining_eligibility_fires_exactly_at_threshold(
        self,
        tenant_id: uuid.UUID,
        finding_id: uuid.UUID,
        mock_connection: any,
        mock_event_publisher: any,
    ) -> None:
        building_id = uuid.uuid4()
        bundle_str = json.dumps({"finding_id": str(finding_id), "top_features": []})

        def get_conn():
            return mock_connection

        # Scenario A: Count is RETRAINING_THRESHOLD - 1 (e.g. 4) -> should NOT fire
        mock_connection.cursor_obj.query_responses = {
            "FROM findings": [[(building_id, bundle_str)]],
            "COUNT(*)": [[(RETRAINING_THRESHOLD - 1,)]],
        }
        service = FeedbackService(
            get_connection=get_conn,
            event_publisher=mock_event_publisher,
        )
        service.record_feedback(
            tenant_id=tenant_id,
            finding_id=finding_id,
            action="confirmed",
            actor="test_user",
        )
        assert len(mock_event_publisher.published_events) == 0

        # Scenario B: Count is RETRAINING_THRESHOLD (e.g. 5) -> should fire EXACTLY
        mock_connection.committed = False
        mock_connection.cursor_obj.query_responses = {
            "FROM findings": [[(building_id, bundle_str)]],
            "COUNT(*)": [[(RETRAINING_THRESHOLD,)]],
        }
        service.record_feedback(
            tenant_id=tenant_id,
            finding_id=finding_id,
            action="confirmed",
            actor="test_user",
        )
        assert len(mock_event_publisher.published_events) == 1
        topic, event = mock_event_publisher.published_events[0]
        assert topic == "model.retraining.eligible"
        assert event.tenant_id == tenant_id
        assert event.building_id == building_id
        assert event.feedback_count == RETRAINING_THRESHOLD
        assert event.retraining_threshold == RETRAINING_THRESHOLD
        assert event.event_type == "model.retraining.eligible"

        # Scenario C: Count is RETRAINING_THRESHOLD + 1 (e.g. 6) -> should NOT fire (only exactly at crossing)
        mock_connection.cursor_obj.query_responses = {
            "FROM findings": [[(building_id, bundle_str)]],
            "COUNT(*)": [[(RETRAINING_THRESHOLD + 1,)]],
        }
        service.record_feedback(
            tenant_id=tenant_id,
            finding_id=finding_id,
            action="confirmed",
            actor="test_user",
        )
        # Count should remain 1 (no new event published)
        assert len(mock_event_publisher.published_events) == 1
