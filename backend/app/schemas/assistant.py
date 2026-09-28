"""Request/response shapes for the Ask HerMedi AI assistant."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class AssistantAskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    language: Literal["en", "hi"] = Field(
        default="en",
        description="Answer language. 'hi' translates the answer (via MyMemory) "
        "and swaps in a Hindi disclaimer after an English answer comes back "
        "from the AI provider.",
    )


class AssistantAskResponse(BaseModel):
    answer: str
    model_used: str
    disclaimer: str
    language: str
