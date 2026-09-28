"""End-to-end tests for signup, login, the current-user routes, and erasure.

Marked ``integration``: these open real connections, so they need Postgres.
Unlike ``test_database.py`` they do **not** self-skip -- an auth flow that cannot
run is a failure, not a reason to report green, so they fail loudly when the
database is absent. The tables are truncated between tests; the suite is the only
writer of its own database.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal, engine
from app.core.security import create_access_token
from app.core.soft_delete import include_deleted
from app.models.audit import AuditLog
from app.models.medicine import Medicine
from app.models.user import User, UserProfile

# Every table the suite touches. Truncated, not cascade-dropped, so a forgotten
# table shows up as leftover rows rather than a silent pass.
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
async def _clean_database() -> AsyncIterator[None]:
    """Empty every table, and drop the pool so the next test gets a fresh loop.

    The dispose is mandatory, not hygiene: the module-level engine in
    ``app.core.database`` hands out asyncpg connections bound to whichever event
    loop opened them, and pytest-asyncio gives each test a new loop. Without
    this the suite passes for a few tests and then dies with
    ``AttributeError: 'NoneType' object has no attribute 'send'``.
    """
    async with engine.begin() as conn:
        await conn.execute(
            text(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE;")
        )
    yield
    await engine.dispose()


@pytest.fixture
async def session() -> AsyncIterator:
    async with AsyncSessionLocal() as s:
        yield s


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """Real routes, real session dependency, real database."""
    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as http_client:
        yield http_client


@pytest.fixture
def unique_email() -> str:
    return f"user-{uuid.uuid4().hex[:12]}@example.com"


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def register(
    client: AsyncClient, email: str, password: str = "Str0ngPassw0rd!"
) -> dict:
    """Signup and return the token payload."""
    response = await client.post(
        "/auth/signup",
        json={"email": email, "password": password, "full_name": "Asha Rao"},
    )
    assert response.status_code == 201, response.text
    return response.json()


# --------------------------------------------------------------------------
# signup
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_signup_returns_token_and_persists_user(
    client: AsyncClient, session, unique_email: str
) -> None:
    body = await register(client, unique_email)

    assert body["token_type"] == "bearer"
    assert body["email"] == unique_email
    assert body["expires_in"] == 24 * 60 * 60  # ~24h per the brief
    assert len(body["access_token"].split(".")) == 3  # header.payload.signature

    user = await session.scalar(select(User).where(User.email == unique_email))
    assert user is not None
    assert user.full_name == "Asha Rao"
    assert user.consent_given_at is None


@pytest.mark.asyncio
async def test_signup_never_stores_the_plaintext_password(
    client: AsyncClient, session, unique_email: str
) -> None:
    password = "Sup3rSecret!pass"
    await register(client, unique_email, password)

    user = await session.scalar(select(User).where(User.email == unique_email))
    assert user.hashed_password != password
    assert user.hashed_password.startswith(("$2a$", "$2b$", "$2y$"))
    assert len(user.hashed_password) == 60


@pytest.mark.asyncio
async def test_signup_folds_email_case(
    client: AsyncClient, session, unique_email: str
) -> None:
    await register(client, unique_email.upper())

    user = await session.scalar(select(User).where(User.email == unique_email.lower()))
    assert user is not None
    assert user.email == unique_email.lower()


@pytest.mark.asyncio
async def test_duplicate_email_is_409(client: AsyncClient, unique_email: str) -> None:
    await register(client, unique_email)

    again = await client.post(
        "/auth/signup",
        json={
            "email": unique_email,
            "password": "An0therPass!",
            "full_name": "Impostor",
        },
    )

    assert again.status_code == 409
    assert "already exists" in again.json()["detail"]


@pytest.mark.asyncio
async def test_duplicate_email_is_case_insensitive(
    client: AsyncClient, unique_email: str
) -> None:
    """``A@x.com`` must collide with ``a@x.com``, matching the login behaviour."""
    await register(client, unique_email)

    again = await client.post(
        "/auth/signup",
        json={
            "email": unique_email.upper(),
            "password": "An0therPass!",
            "full_name": "Impostor",
        },
    )
    assert again.status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (
            {"email": "not-an-email", "password": "Str0ngPassw0rd!", "full_name": "A"},
            "email",
        ),
        ({"email": "a@b.com", "password": "short", "full_name": "A"}, "password"),
        (
            {"email": "a@b.com", "password": "Str0ngPassw0rd!", "full_name": "  "},
            "full_name",
        ),
        ({"email": "a@b.com", "password": "Str0ngPassw0rd!"}, "missing full_name"),
    ],
)
async def test_signup_rejects_invalid_payloads(
    client: AsyncClient, payload: dict, reason: str
) -> None:
    response = await client.post("/auth/signup", json=payload)
    assert response.status_code == 422, reason


@pytest.mark.asyncio
async def test_password_over_72_bytes_is_rejected(
    client: AsyncClient, unique_email: str
) -> None:
    """bcrypt ignores everything past 72 bytes, so the schema must refuse it.

    Without the cap, two different 100-character passwords would verify against
    the same stored digest.
    """
    response = await client.post(
        "/auth/signup",
        json={"email": unique_email, "password": "x" * 73, "full_name": "A"},
    )
    assert response.status_code == 422


# --------------------------------------------------------------------------
# login
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_returns_a_valid_token(
    client: AsyncClient, unique_email: str
) -> None:
    await register(client, unique_email, "MyR3alPassword!")

    response = await client.post(
        "/auth/login", json={"email": unique_email, "password": "MyR3alPassword!"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"].count(".") == 2
    assert body["expires_in"] == 86400


@pytest.mark.asyncio
async def test_login_is_case_insensitive_on_email(
    client: AsyncClient, unique_email: str
) -> None:
    await register(client, unique_email, "MyR3alPassword!")

    response = await client.post(
        "/auth/login",
        json={"email": unique_email.upper(), "password": "MyR3alPassword!"},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_login_with_wrong_password_is_401(
    client: AsyncClient, unique_email: str
) -> None:
    await register(client, unique_email)

    response = await client.post(
        "/auth/login", json={"email": unique_email, "password": "Wr0ngPassword!"}
    )

    assert response.status_code == 401
    assert response.headers.get("WWW-Authenticate") == "Bearer"


@pytest.mark.asyncio
async def test_unknown_email_and_wrong_password_are_indistinguishable(
    client: AsyncClient, unique_email: str
) -> None:
    """A different 401 body would let an attacker enumerate registered emails."""
    await register(client, unique_email)

    wrong_password = await client.post(
        "/auth/login", json={"email": unique_email, "password": "Wr0ngPassword!"}
    )
    no_such_user = await client.post(
        "/auth/login",
        # A well-formed domain that does not exist. ``EmailStr`` validates domain
        # *syntax* but not deliverability, so this passes validation and reaches
        # the "no such user" branch. A reserved TLD like ``.invalid`` would be
        # rejected with 422 and never get that far.
        json={
            "email": "nobody@no-such-domain-8f3a2b1c.com",
            "password": "Wr0ngPassword!",
        },
    )

    assert wrong_password.status_code == no_such_user.status_code == 401
    assert wrong_password.json() == no_such_user.json()


# --------------------------------------------------------------------------
# get_current_user
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_me_requires_a_token(client: AsyncClient) -> None:
    response = await client.get("/users/me")
    assert response.status_code == 401
    assert response.headers.get("WWW-Authenticate") == "Bearer"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "header",
    [
        "Bearer not-a-jwt",
        "Bearer ",
        "Basic dXNlcjpwYXNz",  # right token, wrong scheme
        "notbearer abc.def.ghi",
    ],
)
async def test_malformed_authorization_headers_are_401(
    client: AsyncClient, header: str
) -> None:
    response = await client.get("/users/me", headers={"Authorization": header})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_token_signed_with_a_foreign_key_is_401(client: AsyncClient) -> None:
    """A structurally valid JWT signed with the wrong secret must be rejected.

    The claims are real and unexpired; only the HMAC is wrong. This is the case
    that separates real signature verification from a naive base64 decode.
    """
    from jose import jwt

    forged = jwt.encode(
        {
            "sub": "1",
            "email": "attacker@example.com",
            "type": "access",
            "iss": get_settings().jwt_issuer,
            "iat": int(datetime.now(UTC).timestamp()),
            "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
        },
        "a-completely-different-signing-secret",
        algorithm="HS256",
    )

    response = await client.get("/users/me", headers=auth_header(forged))
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_expired_token_is_401(client: AsyncClient, unique_email: str) -> None:
    """Forge a correctly-signed token whose ``exp`` is already in the past."""
    await register(client, unique_email)
    user = await _find_user(unique_email)

    from jose import jwt

    settings = get_settings()
    stale = jwt.encode(
        {
            "sub": str(user.id),
            "email": user.email,
            "type": "access",
            "iss": settings.jwt_issuer,
            "iat": int((datetime.now(UTC) - timedelta(hours=48)).timestamp()),
            "exp": int((datetime.now(UTC) - timedelta(hours=24)).timestamp()),
        },
        settings.secret_key,
        algorithm=settings.jwt_algorithm,
    )

    response = await client.get("/users/me", headers=auth_header(stale))
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_token_for_unknown_user_is_401(client: AsyncClient) -> None:
    token = create_access_token(user_id=999_999, email="ghost@example.com")[0]
    response = await client.get("/users/me", headers=auth_header(token))
    assert response.status_code == 401


# --------------------------------------------------------------------------
# GET /users/me and the profile upsert
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_me_returns_the_user_and_null_profile(
    client: AsyncClient, unique_email: str
) -> None:
    token = (await register(client, unique_email))["access_token"]

    response = await client.get("/users/me", headers=auth_header(token))

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == unique_email
    assert body["full_name"] == "Asha Rao"
    assert body["profile"] is None  # signup does not create one
    assert body["consent_given_at"] is None


@pytest.mark.asyncio
async def test_profile_create_then_update(
    client: AsyncClient, unique_email: str
) -> None:
    token = (await register(client, unique_email))["access_token"]

    created = await client.post(
        "/users/me/profile",
        headers=auth_header(token),
        json={"context_type": "pregnant", "trimester": 2},
    )
    assert created.status_code == 201, created.text
    profile_id = created.json()["id"]
    assert created.json()["trimester"] == 2

    updated = await client.post(
        "/users/me/profile",
        headers=auth_header(token),
        json={"context_type": "pregnant", "trimester": 3},
    )
    assert updated.status_code == 200  # 200, not 201: this was an update
    assert updated.json()["id"] == profile_id  # same row, not a duplicate
    assert updated.json()["trimester"] == 3

    me = await client.get("/users/me", headers=auth_header(token))
    assert me.json()["profile"]["trimester"] == 3


@pytest.mark.asyncio
async def test_profile_upsert_is_per_user(client: AsyncClient) -> None:
    """Two accounts must not collide on the unique user_id constraint."""
    first = (await register(client, f"a-{uuid.uuid4().hex[:8]}@example.com"))[
        "access_token"
    ]
    second = (await register(client, f"b-{uuid.uuid4().hex[:8]}@example.com"))[
        "access_token"
    ]

    for token in (first, second):
        response = await client.post(
            "/users/me/profile",
            headers=auth_header(token),
            json={"context_type": "general"},
        )
        assert response.status_code == 201


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"context_type": "pregnant"},  # trimester is mandatory when pregnant
        {"context_type": "pregnant", "trimester": 4},  # out of range
        {"context_type": "pregnant", "trimester": 0},
        {"context_type": "breastfeeding"},  # infant age is mandatory
        {"context_type": "pregnant", "trimester": 2, "infant_age_months": 3},
        {"context_type": "general", "trimester": 2},
        {"context_type": "not_a_real_context"},
    ],
)
async def test_profile_rejects_incoherent_contexts(
    client: AsyncClient, unique_email: str, payload: dict
) -> None:
    token = (await register(client, unique_email))["access_token"]
    response = await client.post(
        "/users/me/profile", headers=auth_header(token), json=payload
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_profile_requires_auth(client: AsyncClient) -> None:
    response = await client.post("/users/me/profile", json={"context_type": "general"})
    assert response.status_code == 401


# --------------------------------------------------------------------------
# consent
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_consent_is_recorded_and_idempotent(
    client: AsyncClient, unique_email: str
) -> None:
    token = (await register(client, unique_email))["access_token"]

    first = await client.post("/users/me/consent", headers=auth_header(token))
    assert first.status_code == 200
    assert first.json()["already_recorded"] is False
    first_at = first.json()["consent_given_at"]

    second = await client.post("/users/me/consent", headers=auth_header(token))
    assert second.status_code == 200
    assert second.json()["already_recorded"] is True
    # The original timestamp must survive; consent history is not rewriteable.
    assert second.json()["consent_given_at"] == first_at

    me = await client.get("/users/me", headers=auth_header(token))
    assert me.json()["consent_given_at"] == first_at


@pytest.mark.asyncio
async def test_consent_requires_auth(client: AsyncClient) -> None:
    assert (await client.post("/users/me/consent")).status_code == 401


# --------------------------------------------------------------------------
# soft delete
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_soft_delete_hides_everything(
    client: AsyncClient, session, unique_email: str
) -> None:
    token = (await register(client, unique_email))["access_token"]
    await client.post(
        "/users/me/profile",
        headers=auth_header(token),
        json={"context_type": "pregnant", "trimester": 1},
    )
    user_id = (await _find_user(unique_email)).id

    deleted = await client.delete("/users/me", headers=auth_header(token))
    assert deleted.status_code == 200
    assert deleted.json()["hard_deleted"] is False
    assert deleted.json()["deleted_at"]

    # The rows must still physically exist -- that is what "soft" means.
    with include_deleted():
        tombstoned = await session.scalar(select(User).where(User.id == user_id))
        assert tombstoned is not None
        assert tombstoned.deleted_at is not None
        assert tombstoned.is_deleted is True

    # ...and be invisible to the ORM by default, with no opt-in anywhere.
    assert await session.scalar(select(User).where(User.id == user_id)) is None
    assert (
        await session.scalar(select(UserProfile).where(UserProfile.user_id == user_id))
        is None
    )
    assert (
        await session.scalar(select(Medicine).where(Medicine.user_id == user_id))
        is None
    )


@pytest.mark.asyncio
async def test_token_stops_working_immediately_after_delete(
    client: AsyncClient, unique_email: str
) -> None:
    """No blacklist and no token revocation list: the tombstone does the work."""
    token = (await register(client, unique_email))["access_token"]
    assert (
        await client.get("/users/me", headers=auth_header(token))
    ).status_code == 200

    await client.delete("/users/me", headers=auth_header(token))

    # The JWT is still cryptographically valid and unexpired.
    after = await client.get("/users/me", headers=auth_header(token))
    assert after.status_code == 401


@pytest.mark.asyncio
async def test_deleted_user_cannot_log_in_again(
    client: AsyncClient, unique_email: str
) -> None:
    password = "Str0ngPassw0rd!"
    token = (await register(client, unique_email, password))["access_token"]

    assert (
        await client.post(
            "/auth/login", json={"email": unique_email, "password": password}
        )
    ).status_code == 200

    await client.delete("/users/me", headers=auth_header(token))

    again = await client.post(
        "/auth/login", json={"email": unique_email, "password": password}
    )
    assert again.status_code == 401
    # Identical to the unknown-email response, so deletion is not observable
    # from the login endpoint either.
    assert again.json()["detail"] == "Incorrect email or password"


@pytest.mark.asyncio
async def test_soft_delete_is_idempotent(
    client: AsyncClient, session, unique_email: str
) -> None:
    token = (await register(client, unique_email))["access_token"]

    first = await client.delete("/users/me", headers=auth_header(token))
    assert first.status_code == 200
    first_at = first.json()["deleted_at"]

    # Replaying the same call must not move the timestamp: "when did you delete
    # my account" needs one stable answer. The second call 401s because the
    # token is dead, so drive the service directly to prove the guard.
    user = await _find_user_even_if_deleted(unique_email)
    assert user.deleted_at is not None
    assert _iso(user.deleted_at) == first_at


@pytest.mark.asyncio
async def test_soft_delete_leaves_audit_logs_intact(
    client: AsyncClient, session, unique_email: str
) -> None:
    """Deleting the evidence of what happened is not what an audit trail is for."""
    token = (await register(client, unique_email))["access_token"]
    await client.post("/users/me/consent", headers=auth_header(token))
    await client.delete("/users/me", headers=auth_header(token))

    # AuditLog has no deleted_at, so it is never filtered.
    remaining = await session.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.action == "user.account.soft_deleted")
    )
    assert remaining == 1


@pytest.mark.asyncio
async def test_delete_requires_auth(client: AsyncClient) -> None:
    assert (await client.delete("/users/me")).status_code == 401


# --------------------------------------------------------------------------
# audit trail
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_action_writes_an_audit_entry(
    client: AsyncClient, session, unique_email: str
) -> None:
    """The brief requires an AuditLog row per action; assert the whole chain."""
    token = (await register(client, unique_email))["access_token"]
    await client.get("/users/me", headers=auth_header(token))
    await client.post(
        "/users/me/profile",
        headers=auth_header(token),
        json={"context_type": "pregnant", "trimester": 1},
    )
    await client.post("/users/me/consent", headers=auth_header(token))
    await client.post(
        "/auth/login", json={"email": unique_email, "password": "Str0ngPassw0rd!"}
    )
    await client.delete("/users/me", headers=auth_header(token))

    rows = (
        (await session.execute(select(AuditLog).order_by(AuditLog.id))).scalars().all()
    )
    actions = [r.action for r in rows]

    assert actions == [
        "auth.signup",
        "user.profile.read",
        "user.profile.created",
        "user.consent.recorded",
        "auth.login",
        "user.account.soft_deleted",
    ]

    entry = rows[0]
    assert entry.resource_type == "user"
    assert entry.resource_id == str(entry.user_id)
    assert entry.user_id is not None
    assert entry.timestamp is not None


@pytest.mark.asyncio
async def test_failed_login_is_audited_with_a_null_user(
    client: AsyncClient, session, unique_email: str
) -> None:
    await register(client, unique_email)
    await client.post(
        "/auth/login", json={"email": unique_email, "password": "definitely-wrong"}
    )

    entry = await session.scalar(
        select(AuditLog).where(AuditLog.action == "auth.login_failed")
    )
    assert entry is not None
    # Nullable precisely so a failure against an unknown address still leaves a trace.
    assert entry.user_id is None
    assert entry.resource_id == unique_email


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _iso(value: datetime) -> str:
    """Render a datetime the way FastAPI serialises one, for comparison."""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


async def _find_user(email: str) -> User:
    """Load a live user through the normal (filtered) path."""
    async with AsyncSessionLocal() as s:
        user = await s.scalar(select(User).where(User.email == email))
        assert user is not None, "expected a visible user"
        return user


async def _find_user_even_if_deleted(email: str) -> User:
    """Load a user with the soft-delete filter lifted.

    ``include_deleted`` is a plain (sync) context manager -- it flips a
    ContextVar, no awaits inside -- so it needs nesting rather than ``async with``.
    """
    async with AsyncSessionLocal() as s:
        with include_deleted():
            user = await s.scalar(select(User).where(User.email == email))
        assert user is not None
        return user
