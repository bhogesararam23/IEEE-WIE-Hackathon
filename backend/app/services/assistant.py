"""Ask HerMedi AI: a grounded chat answer over the caller's own safety data.

Two free-tier providers, tried in order. Gemini is primary; if it errors, times
out, or is rate-limited, the exact same prompt is retried against Groq before
giving up. Neither call blocks on anything but the network -- there is no local
model, which matters on the underpowered dev machine this was built on.

Kept out of the router so ``ask`` has one job: take a user and a question, return
grounded text. The router's job is HTTP status codes and auditing.
"""

from __future__ import annotations

import logging
import re

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.models.interaction import InteractionAlert
from app.models.medicine import Medicine
from app.models.user import User, UserProfile

logger = logging.getLogger(__name__)

__all__ = ["AssistantUnavailableError", "DISCLAIMER", "ask"]

DISCLAIMER = (
    "This is general information, not a diagnosis or prescription. For anything "
    "urgent, or before starting, stopping, or changing a medicine, check with "
    "your doctor or pharmacist."
)

# A real MyMemory translation of DISCLAIMER, captured once rather than requested
# on every Hindi answer: the English text never changes, so re-translating it
# per request would just burn free-tier quota for an identical result.
_DISCLAIMER_HI = (
    "यह सामान्य जानकारी है, निदान या पर्चे नहीं। किसी भी जरूरी चीज़ के लिए, या दवा "
    "शुरू करने, रोकने या बदलने से पहले, अपने डॉक्टर या फार्मासिस्ट से संपर्क करें।"
)

_SYSTEM_PROMPT = """You are HerMedi AI, a safety-focused assistant inside the \
HerMediSafe app for women's medicine safety during pregnancy, breastfeeding, and \
general use.

Rules you must follow:
- You are given the caller's current maternal context, confirmed medicines, and \
active interaction alerts below. Ground your answer in that data when relevant.
- Never diagnose a condition, never prescribe or recommend starting/stopping a \
specific medicine, and never contradict a HIGH severity alert already on file.
- If the question concerns a HIGH severity alert or describes an emergency \
symptom, say plainly that this needs a doctor or pharmacist, and do not attempt \
a workaround.
- Answer in plain language, in 3-6 short sentences. No markdown headers.
- If you don't have enough information from the context to answer safely, say \
so instead of guessing.
"""

_REQUEST_TIMEOUT = httpx.Timeout(20.0, connect=10.0)


class AssistantUnavailableError(RuntimeError):
    """Neither AI provider is configured, or both requests failed."""


async def _build_context(session: AsyncSession, *, user: User) -> str:
    """Summarise the caller's profile, active medicines, and alerts as plain text."""
    lines: list[str] = []

    # Queried directly rather than through `user.profile`: the current-user
    # dependency does not eager-load it, and touching a lazy relationship here
    # would raise MissingGreenlet under async SQLAlchemy.
    profile = await session.scalar(
        select(UserProfile).where(UserProfile.user_id == user.id)
    )
    if profile is not None:
        context_bits = [f"maternal context: {profile.context_type.value}"]
        if profile.trimester is not None:
            context_bits.append(f"trimester {profile.trimester}")
        if profile.infant_age_months is not None:
            context_bits.append(f"infant age {profile.infant_age_months} months")
        lines.append(", ".join(context_bits))
    else:
        lines.append("maternal context: not set")

    medicines = list(
        (
            await session.scalars(
                select(Medicine).where(
                    Medicine.user_id == user.id,
                    Medicine.is_confirmed.is_(True),
                )
            )
        ).all()
    )
    if medicines:
        med_lines = ", ".join(
            f"{m.raw_name}"
            + (f" ({m.normalized_ingredient})" if m.normalized_ingredient else "")
            + (f", {m.frequency}" if m.frequency else "")
            for m in medicines
        )
        lines.append(f"confirmed medicines: {med_lines}")
    else:
        lines.append("confirmed medicines: none on file")

    alerts = list(
        (
            await session.scalars(
                select(InteractionAlert)
                .where(InteractionAlert.user_id == user.id)
                .options(selectinload(InteractionAlert.medicines))
            )
        ).all()
    )
    if alerts:
        alert_lines = "; ".join(
            f"{a.severity.value.upper()} severity between "
            f"{' + '.join(m.raw_name for m in a.medicines)}: {a.rationale}"
            for a in alerts
        )
        lines.append(f"active interaction alerts: {alert_lines}")
    else:
        lines.append("active interaction alerts: none")

    return "\n".join(lines)


async def _call_gemini(
    client: httpx.AsyncClient, *, api_key: str, model: str, question: str, context: str
) -> str:
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    )
    response = await client.post(
        url,
        params={"key": api_key},
        json={
            "system_instruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": f"Context:\n{context}\n\nQuestion: {question}"}],
                }
            ],
            "generationConfig": {
                "temperature": 0.3,
                "maxOutputTokens": 512,
                # Current Gemini flash models spend part of maxOutputTokens on
                # hidden reasoning before the visible answer, which silently
                # truncated replies here. This is a short grounded-lookup
                # answer, not a reasoning task, so thinking buys nothing.
                "thinkingConfig": {"thinkingBudget": 0},
            },
        },
        timeout=_REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()
    return data["candidates"][0]["content"]["parts"][0]["text"].strip()


async def _call_groq(
    client: httpx.AsyncClient, *, api_key: str, model: str, question: str, context: str
) -> str:
    response = await client.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Context:\n{context}\n\nQuestion: {question}",
                },
            ],
            "temperature": 0.3,
            "max_tokens": 512,
        },
        timeout=_REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"].strip()


_MYMEMORY_URL = "https://api.mymemory.translated.net/get"
# MyMemory's anonymous tier caps a single `q` value at 500 bytes; the answer
# (up to ~512 Gemini output tokens) can exceed that, so it is translated in
# sentence-sized chunks rather than one request.
_MYMEMORY_MAX_BYTES = 480


def _sentence_chunks(text: str, max_bytes: int = _MYMEMORY_MAX_BYTES) -> list[str]:
    """Group ``text`` into chunks that each fit under ``max_bytes``, on sentence
    boundaries where possible so a translated chunk never cuts mid-sentence."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        candidate = f"{current} {sentence}".strip() if current else sentence
        if current and len(candidate.encode("utf-8")) > max_bytes:
            chunks.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


async def _translate_to_hindi(client: httpx.AsyncClient, text: str) -> str:
    """Translate ``text`` to Hindi via MyMemory, chunked to its request cap.

    Fails soft per chunk: a timeout or bad response leaves that chunk in
    English rather than raising, since a translation hiccup must never break
    an otherwise-successful answer.
    """
    translated_parts: list[str] = []
    for chunk in _sentence_chunks(text):
        try:
            response = await client.get(
                _MYMEMORY_URL,
                params={"q": chunk, "langpair": "en|hi"},
                timeout=_REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            translated = response.json()["responseData"]["translatedText"]
            translated_parts.append(translated or chunk)
        except (httpx.HTTPError, KeyError, TypeError) as exc:
            logger.warning(
                "Hindi translation failed for a chunk, keeping English: %s", exc
            )
            translated_parts.append(chunk)
    return " ".join(translated_parts)


async def ask(
    session: AsyncSession, *, user: User, question: str, language: str = "en"
) -> tuple[str, str, str]:
    """Answer ``question`` grounded in the caller's data.

    Returns ``(answer, model_used, disclaimer)``.

    Tries Gemini first, then Groq. Raises :class:`AssistantUnavailableError` if
    neither provider is configured or both calls fail -- the router turns that
    into a 503 rather than a fabricated answer. ``language="hi"`` translates
    the finished English answer (and swaps in the Hindi disclaimer) as a
    separate, fail-soft step after a provider has already answered -- it is
    never baked into the Gemini/Groq prompt itself.
    """
    settings = get_settings()
    context = await _build_context(session, user=user)

    if not settings.gemini_api_key and not settings.groq_api_key:
        raise AssistantUnavailableError(
            "No AI provider configured. Set GEMINI_API_KEY or GROQ_API_KEY."
        )

    answer: str | None = None
    model_used: str | None = None

    async with httpx.AsyncClient() as client:
        if settings.gemini_api_key:
            try:
                answer = await _call_gemini(
                    client,
                    api_key=settings.gemini_api_key,
                    model=settings.gemini_model,
                    question=question,
                    context=context,
                )
                model_used = "gemini"
            except (httpx.HTTPError, KeyError, IndexError) as exc:
                logger.warning("Gemini call failed, falling back to Groq: %s", exc)

        if answer is None and settings.groq_api_key:
            try:
                answer = await _call_groq(
                    client,
                    api_key=settings.groq_api_key,
                    model=settings.groq_model,
                    question=question,
                    context=context,
                )
                model_used = "groq"
            except (httpx.HTTPError, KeyError, IndexError) as exc:
                logger.warning("Groq call failed: %s", exc)

        if answer is None or model_used is None:
            raise AssistantUnavailableError(
                "The AI assistant is temporarily unavailable."
            )

        disclaimer = DISCLAIMER
        if language == "hi":
            answer = await _translate_to_hindi(client, answer)
            disclaimer = _DISCLAIMER_HI

    return answer, model_used, disclaimer
