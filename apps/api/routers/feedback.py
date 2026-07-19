"""ENG-5b — Feedback API (TRD v2.0 §7.1): confirm/dismiss findings. Thin
wrapper over the async FeedbackService built in ENG-5's Phase 0 prerequisite
refactor -- the router's only job is auth/tenant-scoping plumbing.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies import get_current_claims, get_event_publisher, get_tenant_scoped_session
from orchestration.events.kafka.producer import EventPublisher
from services.feedback.repository import FeedbackRepository
from services.feedback.service import FeedbackService
from shared.auth.jwt import TokenClaims

router = APIRouter(prefix="/v1/feedback", tags=["feedback"])


class FeedbackRequest(BaseModel):
    finding_id: UUID
    action: str


class FeedbackResponse(BaseModel):
    finding_id: UUID
    action: str


@router.post("", response_model=FeedbackResponse, status_code=status.HTTP_200_OK)
async def submit_feedback(
    body: FeedbackRequest,
    claims: TokenClaims = Depends(get_current_claims),
    session: AsyncSession = Depends(get_tenant_scoped_session),
    event_publisher: EventPublisher = Depends(get_event_publisher),
) -> FeedbackResponse:
    service = FeedbackService(
        repository=FeedbackRepository(session), event_publisher=event_publisher
    )
    await service.record_feedback(
        tenant_id=claims.tenant_id,
        finding_id=body.finding_id,
        action=body.action,
        actor=claims.subject,
    )
    return FeedbackResponse(finding_id=body.finding_id, action=body.action)
