from __future__ import annotations

import datetime
import json
import logging
import uuid
from typing import Any, Callable

from orchestration.events.kafka.schemas.retraining_eligible import RetrainingEligibleEvent

logger = logging.getLogger(__name__)

# UNRATIFIED CONFIG CONSTANT: Crossing this number of feedback labels for a building triggers retraining.
RETRAINING_THRESHOLD = 5


class FeedbackService:
    """Manages recording feedback labels (confirm/dismiss) on findings.

    Enforces that the target finding has an explainability bundle before writing,
    maintains a per-building feedback counter, and fires retraining-eligibility events
    exactly at the threshold crossing.
    """

    def __init__(
        self,
        get_connection: Callable[[], Any],
        event_publisher: Any = None,
        kafka_settings: Any = None,
    ) -> None:
        self.get_connection = get_connection
        self.event_publisher = event_publisher
        self.kafka_settings = kafka_settings

    def record_feedback(
        self,
        tenant_id: uuid.UUID,
        finding_id: uuid.UUID,
        action: str,
        actor: str,
    ) -> None:
        """Records confirm/dismiss feedback for a finding.

        Ensures the finding is valid, has an explainability bundle, inserts the feedback label,
        updates the finding status, and publishes a retraining-eligible event if the threshold is reached.
        """
        if action not in ("confirmed", "dismissed"):
            raise ValueError(f"Invalid feedback action: {action}")

        conn = self.get_connection()
        try:
            # Detect connection type
            is_sqlalchemy = hasattr(conn, "execute") and not hasattr(conn, "cursor")

            if is_sqlalchemy:
                from sqlalchemy import text

                # Set RLS tenant context
                conn.execute(
                    text("SET LOCAL app.current_tenant_id = :tid"),
                    {"tid": str(tenant_id)},
                )

                # Fetch findings row to verify is_eligible
                res = conn.execute(
                    text(
                        "SELECT building_id, explainability_bundle "
                        "FROM findings "
                        "WHERE finding_id = :fid"
                    ),
                    {"fid": str(finding_id)},
                )
                row = res.fetchone()
            else:
                cursor = conn.cursor()
                cursor.execute(
                    "SET LOCAL app.current_tenant_id = %s", (str(tenant_id),)
                )
                cursor.execute(
                    "SELECT building_id, explainability_bundle "
                    "FROM findings "
                    "WHERE finding_id = %s",
                    (str(finding_id),),
                )
                row = cursor.fetchone()

            if not row:
                raise ValueError(
                    f"Finding with ID {finding_id} was not found or is not visible to this tenant."
                )

            building_id = row[0]
            explainability_bundle_raw = row[1]

            # In psycopg2/SQLAlchemy, JSONB might be returned as dict or parsed json object. Let's make sure:
            if isinstance(explainability_bundle_raw, str):
                try:
                    explainability_bundle = json.loads(explainability_bundle_raw)
                except json.JSONDecodeError:
                    explainability_bundle = None
            else:
                explainability_bundle = explainability_bundle_raw

            is_valid_bundle = (
                explainability_bundle is not None
                and isinstance(explainability_bundle, dict)
                and len(explainability_bundle) > 0
            )

            if not is_valid_bundle:
                raise ValueError(
                    f"Cannot write feedback for finding {finding_id} because it has no explainability bundle."
                )

            # Insert into feedback_labels & update finding status
            feedback_id = uuid.uuid4()
            now = datetime.datetime.now(datetime.timezone.utc)

            if is_sqlalchemy:
                conn.execute(
                    text(
                        "INSERT INTO feedback_labels "
                        "(feedback_id, tenant_id, finding_id, action, actor, created_at) "
                        "VALUES (:fid, :tid, :finding_id, :action, :actor, :created_at)"
                    ),
                    {
                        "fid": str(feedback_id),
                        "tid": str(tenant_id),
                        "finding_id": str(finding_id),
                        "action": action,
                        "actor": actor,
                        "created_at": now,
                    },
                )
                conn.execute(
                    text("UPDATE findings SET status = :status WHERE finding_id = :fid"),
                    {"status": action, "fid": str(finding_id)},
                )

                # Fetch count of feedback labels for this building
                count_res = conn.execute(
                    text(
                        "SELECT COUNT(*) FROM feedback_labels fl "
                        "JOIN findings f ON fl.finding_id = f.finding_id "
                        "WHERE f.building_id = :bid AND fl.tenant_id = :tid"
                    ),
                    {"bid": str(building_id), "tid": str(tenant_id)},
                )
                feedback_count = count_res.scalar()
            else:
                cursor.execute(
                    "INSERT INTO feedback_labels "
                    "(feedback_id, tenant_id, finding_id, action, actor, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (
                        str(feedback_id),
                        str(tenant_id),
                        str(finding_id),
                        action,
                        actor,
                        now,
                    ),
                )
                cursor.execute(
                    "UPDATE findings SET status = %s WHERE finding_id = %s",
                    (action, str(finding_id)),
                )

                cursor.execute(
                    "SELECT COUNT(*) FROM feedback_labels fl "
                    "JOIN findings f ON fl.finding_id = f.finding_id "
                    "WHERE f.building_id = %s AND fl.tenant_id = %s",
                    (str(building_id), str(tenant_id)),
                )
                feedback_count = cursor.fetchone()[0]

            logger.info(
                "Feedback recorded for building %s. Current feedback label count: %s",
                building_id,
                feedback_count,
            )

            # Check if event needs to trigger (exactly at threshold)
            if feedback_count == RETRAINING_THRESHOLD:
                self._publish_retraining_eligible(
                    tenant_id=tenant_id,
                    building_id=building_id,
                    feedback_count=feedback_count,
                )

            # Commit transaction if we are using manual transaction control
            if not is_sqlalchemy and hasattr(conn, "commit"):
                conn.commit()

        except Exception as e:
            if not is_sqlalchemy and hasattr(conn, "rollback"):
                conn.rollback()
            raise e
        finally:
            conn.close()

    def _publish_retraining_eligible(
        self,
        tenant_id: uuid.UUID,
        building_id: uuid.UUID,
        feedback_count: int,
    ) -> None:
        """Publishes the retraining eligible event to the Kafka backbone."""
        if self.event_publisher is None:
            logger.warning(
                "No event publisher configured, skipping RetrainingEligibleEvent publication."
            )
            return

        event = RetrainingEligibleEvent(
            event_id=uuid.uuid4(),
            tenant_id=tenant_id,
            building_id=building_id,
            correlation_id=uuid.uuid4(),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
            event_type="model.retraining.eligible",
            feedback_count=feedback_count,
            retraining_threshold=RETRAINING_THRESHOLD,
        )

        topic = "model.retraining.eligible"
        if self.kafka_settings and hasattr(self.kafka_settings, "topic_retraining_eligible"):
            topic = self.kafka_settings.topic_retraining_eligible
        elif self.kafka_settings and hasattr(self.kafka_settings, "topic_data_arrived"):
            # Default or fallback in configuration
            pass

        self.event_publisher.publish(topic, event)
        logger.info("Published RetrainingEligibleEvent for building %s - count %s", building_id, feedback_count)
