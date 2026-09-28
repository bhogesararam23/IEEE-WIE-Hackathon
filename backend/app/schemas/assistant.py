"""Request/response shapes for the Ask HerMedi AI assistant."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AssistantAskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)


class AssistantAskResponse(BaseModel):
    answer: str
    model_used: str
    disclaimer: str
