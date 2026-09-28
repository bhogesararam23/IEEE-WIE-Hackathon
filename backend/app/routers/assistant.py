"""Ask HerMedi AI: grounded Q&A over the caller's own medicines and alerts."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, status

from app.core.deps import CurrentUser, DbSession, client_ip
from app.schemas.assistant import AssistantAskRequest, AssistantAskResponse
from app.services import assistant as assistant_service
from app.services.audit import AuditAction, record

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/assistant", tags=["assistant"])


@router.post(
    "/ask",
    response_model=AssistantAskResponse,
    status_code=status.HTTP_200_OK,
    summary="Ask a health question grounded in the caller's medicines and alerts",
    responses={
        200: {"description": "Answer from the AI assistant."},
        401: {"description": "Not authenticated."},
        503: {"description": "No AI provider configured, or both providers failed."},
    },
)
async def ask_assistant(
    payload: AssistantAskRequest,
    request: Request,
    user: CurrentUser,
    session: DbSession,
) -> AssistantAskResponse:
    """Answer ``payload.question`` using Gemini, falling back to Groq.

    The question itself is not persisted -- only the fact that one was asked is
    audited, consistent with every other write in this API.
    """
    try:
        answer, model_used = await assistant_service.ask(
            session, user=user, question=payload.question
        )
    except assistant_service.AssistantUnavailableError as exc:
        logger.error("Assistant unavailable for user %s: %s", user.id, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    await record(
        session,
        action=AuditAction.ASSISTANT_QUESTION_ASKED,
        resource_type="assistant_question",
        resource_id=user.id,
        user_id=user.id,
        ip_address=client_ip(request),
    )
    await session.commit()

    return AssistantAskResponse(
        answer=answer,
        model_used=model_used,
        disclaimer=assistant_service.DISCLAIMER,
    )
