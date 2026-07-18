from __future__ import annotations

import datetime
import logging
import uuid

from orchestration.events.kafka.producer import EventPublisher
from orchestration.events.kafka.schemas.retraining_eligible import RetrainingEligibleEvent
from services.feedback.repository import FeedbackRepository
from shared.config.kafka import KafkaSettings

logger = logging.getLogger(__name__)

# UNRATIFIED CONFIG CONSTANT: crossing this number of feedback labels for a
# building triggers retraining. Needs Product/Data Science sign-off before
# GA (Data & Model Strategy 8.1 flags the feedback-volume threshold as an
# open parameter, not yet numerically specified anywhere).
RETRAINING_THRESHOLD = 5


class InvalidFeedbackActionError(ValueError):
    pass


class FindingNotFoundError(ValueError):
    pass


class MissingExplainabilityBundleError(ValueError):
    pass


class FeedbackService:
    """Manages recording feedback labels (confirm/dismiss) on findings.

    Enforces that the target finding has an explainability bundle before
    writing, maintains a per-building feedback counter, and fires
    retraining-eligibility events exactly at the threshold crossing.

    Async + repository-injected, matching every other post-ENG-2c service
    (CalibrationService, OptimizationService, DomainRuleEngineService) --
    the caller is responsible for opening the session inside
    shared.auth.tenant_context.tenant_scope(session, tenant_id) and
    committing afterward, exactly as confidence_calibration_activity and
    optimization_activity already do. Replaces the previous sync,
    dual-connection-type implementation (raw DB-API cursor or sync
    SQLAlchemy Connection, manually issuing `SET LOCAL
    app.current_tenant_id`), which predated that convention.
    """

    def __init__(
        self,
        repository: FeedbackRepository,
        event_publisher: EventPublisher | None = None,
        kafka_settings: KafkaSettings | None = None,
    ) -> None:
        self._repository = repository
        self._event_publisher = event_publisher
        self._kafka_settings = kafka_settings or KafkaSettings()

    async def record_feedback(
        self,
        tenant_id: uuid.UUID,
        finding_id: uuid.UUID,
        action: str,
        actor: str,
    ) -> None:
        """Records confirm/dismiss feedback for a finding.

        Raises:
            InvalidFeedbackActionError: action is not "confirmed"/"dismissed".
            FindingNotFoundError: no finding with this ID is visible to the
                caller's tenant (RLS-enforced by the caller's tenant_scope()).
            MissingExplainabilityBundleError: the finding has no bundle --
                per the same TRD v2.0 §3.7 invariant BundleAssembler enforces
                at write time, feedback cannot be recorded against a finding
                that was never fully assembled.
        """
        if action not in ("confirmed", "dismissed"):
            raise InvalidFeedbackActionError(f"Invalid feedback action: {action}")

        finding = await self._repository.get_finding_for_feedback(finding_id)
        if finding is None:
            raise FindingNotFoundError(
                f"Finding with ID {finding_id} was not found or is not visible to this tenant."
            )

        is_valid_bundle = (
            finding.explainability_bundle is not None
            and isinstance(finding.explainability_bundle, dict)
            and len(finding.explainability_bundle) > 0
        )
        if not is_valid_bundle:
            raise MissingExplainabilityBundleError(
                f"Cannot write feedback for finding {finding_id} because it "
                "has no explainability bundle."
            )

        feedback_id = uuid.uuid4()
        now = datetime.datetime.now(datetime.UTC)

        await self._repository.save_feedback_label(
            feedback_id=feedback_id,
            tenant_id=tenant_id,
            finding_id=finding_id,
            action=action,
            actor=actor,
            created_at=now,
        )
        await self._repository.update_finding_status(finding_id, action)

        feedback_count = await self._repository.count_feedback_for_building(
            tenant_id, finding.building_id
        )

        logger.info(
            "Feedback recorded for building %s. Current feedback label count: %s",
            finding.building_id,
            feedback_count,
        )

        if feedback_count == RETRAINING_THRESHOLD:
            self._publish_retraining_eligible(
                tenant_id=tenant_id,
                building_id=finding.building_id,
                feedback_count=feedback_count,
            )

    def _publish_retraining_eligible(
        self,
        tenant_id: uuid.UUID,
        building_id: uuid.UUID,
        feedback_count: int,
    ) -> None:
        """Publishes the retraining eligible event to the Kafka backbone."""
        if self._event_publisher is None:
            logger.warning(
                "No event publisher configured, skipping RetrainingEligibleEvent publication."
            )
            return

        event = RetrainingEligibleEvent(
            event_id=uuid.uuid4(),
            tenant_id=tenant_id,
            building_id=building_id,
            correlation_id=uuid.uuid4(),
            timestamp=datetime.datetime.now(datetime.UTC),
            event_type="model.retraining.eligible",
            feedback_count=feedback_count,
            retraining_threshold=RETRAINING_THRESHOLD,
        )
        self._event_publisher.publish(self._kafka_settings.topic_retraining_eligible, event)
        logger.info(
            "Published RetrainingEligibleEvent for building %s - count %s",
            building_id,
            feedback_count,
        )
