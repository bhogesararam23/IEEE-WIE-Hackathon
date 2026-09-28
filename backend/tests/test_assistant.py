"""Tests for POST /assistant/ask.

Network calls to Gemini/Groq are never made for real here -- the two provider
functions are monkeypatched at the module level, so these tests exercise
routing, fallback, auditing, and context-building without needing live keys or
a live network.
"""

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import engine
from app.services import assistant as assistant_service

_TABLES = (
    "audit_logs",
    "evidence_references",
    "interaction_alert_medicines",
    "interaction_alerts",
    "duplicate_flags",
    "medicines",
    "prescriptions",
    "reminder_schedules",
    "user_profiles",
    "users",
)


@pytest.fixture(autouse=True)
async def _isolated(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    """Empty the database and reset the cached settings between tests."""
    async with engine.begin() as conn:
        await conn.execute(
            text(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE;")
        )
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
    await engine.dispose()


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def register(client: AsyncClient) -> str:
    email = f"user-{uuid.uuid4().hex[:12]}@example.com"
    response = await client.post(
        "/auth/signup",
        json={"email": email, "password": "Str0ngPassw0rd!", "full_name": "Asha Rao"},
    )
    assert response.status_code == 201, response.text
    return response.json()["access_token"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ask_requires_authentication(client: AsyncClient) -> None:
    response = await client.post("/assistant/ask", json={"question": "hello"})
    assert response.status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ask_503_when_no_provider_configured(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GROQ_API_KEY", "")
    get_settings.cache_clear()

    token = await register(client)
    response = await client.post(
        "/assistant/ask", json={"question": "Is it safe?"}, headers=auth(token)
    )
    assert response.status_code == 503


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ask_uses_gemini_when_it_succeeds(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini-key")
    monkeypatch.setenv("GROQ_API_KEY", "fake-groq-key")
    get_settings.cache_clear()

    async def fake_gemini(client, **kwargs):  # noqa: ANN001, ARG001
        return "Paracetamol alone is commonly used in pregnancy."

    async def fail_groq(client, **kwargs):  # noqa: ANN001, ARG001
        raise AssertionError("Groq should not be called when Gemini succeeds")

    monkeypatch.setattr(assistant_service, "_call_gemini", fake_gemini)
    monkeypatch.setattr(assistant_service, "_call_groq", fail_groq)

    token = await register(client)
    response = await client.post(
        "/assistant/ask",
        json={"question": "Can I take paracetamol?"},
        headers=auth(token),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["model_used"] == "gemini"
    assert "Paracetamol" in body["answer"]
    assert body["disclaimer"] == assistant_service.DISCLAIMER

    audit = await client.get("/audit-logs", headers=auth(token))
    actions = [row["action"] for row in audit.json()["items"]]
    assert "assistant.question_asked" in actions


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ask_falls_back_to_groq_when_gemini_fails(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini-key")
    monkeypatch.setenv("GROQ_API_KEY", "fake-groq-key")
    get_settings.cache_clear()

    async def broken_gemini(client, **kwargs):  # noqa: ANN001, ARG001
        raise httpx.ConnectTimeout("gemini timed out")

    async def fake_groq(client, **kwargs):  # noqa: ANN001, ARG001
        return "Answered by the fallback provider."

    monkeypatch.setattr(assistant_service, "_call_gemini", broken_gemini)
    monkeypatch.setattr(assistant_service, "_call_groq", fake_groq)

    token = await register(client)
    response = await client.post(
        "/assistant/ask", json={"question": "hello"}, headers=auth(token)
    )
    assert response.status_code == 200, response.text
    assert response.json()["model_used"] == "groq"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ask_503_when_both_providers_fail(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini-key")
    monkeypatch.setenv("GROQ_API_KEY", "fake-groq-key")
    get_settings.cache_clear()

    async def broken(client, **kwargs):  # noqa: ANN001, ARG001
        raise httpx.ConnectTimeout("down")

    monkeypatch.setattr(assistant_service, "_call_gemini", broken)
    monkeypatch.setattr(assistant_service, "_call_groq", broken)

    token = await register(client)
    response = await client.post(
        "/assistant/ask", json={"question": "hello"}, headers=auth(token)
    )
    assert response.status_code == 503


@pytest.mark.integration
@pytest.mark.asyncio
async def test_context_includes_profile_medicines_and_alerts(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The prompt sent to the provider should reflect the caller's real data."""
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini-key")
    get_settings.cache_clear()

    token = await register(client)
    await client.post(
        "/users/me/profile",
        json={"context_type": "pregnant", "trimester": 2},
        headers=auth(token),
    )
    await client.post(
        "/medicines",
        json={"raw_name": "Crocin 500mg", "strength": "500mg"},
        headers=auth(token),
    )
    await client.post(
        "/medicines",
        json={"raw_name": "Disprin 325", "strength": "325mg"},
        headers=auth(token),
    )
    await client.post("/medicines/check-interactions", headers=auth(token))

    captured: dict[str, str] = {}

    async def capturing_gemini(client, *, context, **kwargs):  # noqa: ANN001, ARG001
        captured["context"] = context
        return "ok"

    monkeypatch.setattr(assistant_service, "_call_gemini", capturing_gemini)

    response = await client.post(
        "/assistant/ask", json={"question": "hello"}, headers=auth(token)
    )
    assert response.status_code == 200, response.text
    context = captured["context"]
    assert "pregnant" in context
    assert "trimester 2" in context
    assert "Crocin" in context
    assert "Disprin" in context
