"""Tests for the Jan Aushadhi generic-price lookup and its wiring onto Medicine."""

import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.database import engine
from app.services.jan_aushadhi import lookup_generic

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


def test_lookup_generic_matches_known_ingredient() -> None:
    option = lookup_generic("Ciprofloxacin")
    assert option is not None
    assert option.product_name == "Ciprofloxacin Tablets IP 500mg"
    assert option.unit == "strip of 10 tablets"
    assert option.mrp_inr == pytest.approx(24.99)


def test_lookup_generic_is_case_insensitive() -> None:
    assert lookup_generic("PARACETAMOL") is not None
    assert lookup_generic("paracetamol") is not None


def test_lookup_generic_returns_none_for_unmapped_ingredient() -> None:
    assert lookup_generic("Hydroxyzine") is None


def test_lookup_generic_returns_none_for_missing_ingredient() -> None:
    assert lookup_generic(None) is None
    assert lookup_generic("") is None


@pytest.fixture(autouse=True)
async def _isolated() -> AsyncIterator[None]:
    async with engine.begin() as conn:
        await conn.execute(
            text(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE;")
        )
    yield
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
async def test_confirmed_medicine_carries_jan_aushadhi_option(
    client: AsyncClient,
) -> None:
    token = await register(client)
    response = await client.post(
        "/medicines",
        json={"raw_name": "Cifran 500", "strength": "500mg"},
        headers=auth(token),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["normalized_ingredient"] == "Ciprofloxacin"
    assert body["jan_aushadhi"] == {
        "product_name": "Ciprofloxacin Tablets IP 500mg",
        "unit": "strip of 10 tablets",
        "mrp_inr": 24.99,
    }


@pytest.mark.integration
@pytest.mark.asyncio
async def test_medicine_with_unmapped_generic_has_no_jan_aushadhi_option(
    client: AsyncClient,
) -> None:
    token = await register(client)
    response = await client.post(
        "/medicines",
        json={"raw_name": "Atarax 25", "strength": "25mg"},
        headers=auth(token),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["normalized_ingredient"] == "Hydroxyzine"
    assert body["jan_aushadhi"] is None
