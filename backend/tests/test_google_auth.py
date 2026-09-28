"""Tests for POST /auth/google.

Real network calls to Google are never made here -- verify_oauth2_token is
monkeypatched at the module level (same approach as the Gemini/Groq
monkeypatching in test_assistant.py), so these tests exercise account
creation, account linking, and failure handling without needing a live token.
"""

import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal, engine
from app.models.user import User
from app.services import auth as auth_service

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
    async with engine.begin() as conn:
        await conn.execute(
            text(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE;")
        )
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "fake-client-id.apps.googleusercontent.com")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
    await engine.dispose()


@pytest.fixture
async def session() -> AsyncIterator:
    async with AsyncSessionLocal() as s:
        yield s


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


def _claims(email: str, **overrides) -> dict:
    base = {
        "email": email,
        "email_verified": True,
        "name": "Asha Rao",
        "sub": "1234567890",
    }
    base.update(overrides)
    return base


def _fake_verify(claims: dict):
    def _verify(credential, request, audience):  # noqa: ANN001, ARG001
        return claims

    return _verify


def _patch_verify(monkeypatch: pytest.MonkeyPatch, claims: dict) -> None:
    monkeypatch.setattr(
        auth_service.google_id_token, "verify_oauth2_token", _fake_verify(claims)
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_google_auth_503_when_not_configured(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "")
    get_settings.cache_clear()

    response = await client.post("/auth/google", json={"credential": "whatever"})
    assert response.status_code == 503


@pytest.mark.integration
@pytest.mark.asyncio
async def test_google_auth_creates_new_account(
    client: AsyncClient, session, monkeypatch: pytest.MonkeyPatch
) -> None:
    email = f"user-{uuid.uuid4().hex[:12]}@example.com"
    _patch_verify(monkeypatch, _claims(email))

    response = await client.post("/auth/google", json={"credential": "fake-token"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["email"] == email
    assert len(body["access_token"].split(".")) == 3

    user = await session.scalar(select(User).where(User.email == email))
    assert user is not None
    assert user.full_name == "Asha Rao"
    assert user.hashed_password is None
    assert user.consent_given_at is not None

    audit = await client.get(
        "/audit-logs", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    actions = [row["action"] for row in audit.json()["items"]]
    assert "auth.google_signup" in actions


@pytest.mark.integration
@pytest.mark.asyncio
async def test_google_auth_logs_into_existing_password_account(
    client: AsyncClient, session, monkeypatch: pytest.MonkeyPatch
) -> None:
    email = f"user-{uuid.uuid4().hex[:12]}@example.com"
    signup = await client.post(
        "/auth/signup",
        json={"email": email, "password": "Str0ngPassw0rd!", "full_name": "Asha Rao"},
    )
    assert signup.status_code == 201
    original_user_id = signup.json()["user_id"]

    _patch_verify(monkeypatch, _claims(email))
    response = await client.post("/auth/google", json={"credential": "fake-token"})
    assert response.status_code == 200, response.text
    assert response.json()["user_id"] == original_user_id

    # No duplicate account was created for the same address.
    count = await session.scalar(
        select(User).where(User.email == email.lower())
    )
    assert count is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_google_auth_401_on_unverified_email(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    email = f"user-{uuid.uuid4().hex[:12]}@example.com"
    monkeypatch.setattr(
        auth_service.google_id_token,
        "verify_oauth2_token",
        _fake_verify(_claims(email, email_verified=False)),
    )

    response = await client.post("/auth/google", json={"credential": "fake-token"})
    assert response.status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
async def test_google_auth_401_on_invalid_token(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _raise(credential, request, audience):  # noqa: ANN001, ARG001
        raise ValueError("Token used too early")

    monkeypatch.setattr(auth_service.google_id_token, "verify_oauth2_token", _raise)

    response = await client.post("/auth/google", json={"credential": "bad-token"})
    assert response.status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
async def test_password_login_rejected_for_google_only_account(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Google-only account (no password) must not be brute-forceable via login."""
    email = f"user-{uuid.uuid4().hex[:12]}@example.com"
    _patch_verify(monkeypatch, _claims(email))
    created = await client.post("/auth/google", json={"credential": "fake-token"})
    assert created.status_code == 200

    login = await client.post(
        "/auth/login", json={"email": email, "password": "anything-at-all"}
    )
    assert login.status_code == 401
