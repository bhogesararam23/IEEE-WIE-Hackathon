"""End-to-end tests for upload, OCR review, reconciliation, and deletion.

Marked ``integration``: these open real connections and write real files, so they
need Postgres. The tables are truncated between tests and the storage root is
redirected into a pytest tmp dir, so nothing survives a run and the repository's
own ``storage/`` is never touched.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal, engine
from app.core.soft_delete import include_deleted
from app.models.audit import AuditLog
from app.models.enums import MedicineStatus
from app.models.medicine import DuplicateFlag, Medicine
from app.models.prescription import Prescription
from app.services.storage import reset_storage_service

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 256
PDF = b"%PDF-1.7\n" + b"\x00" * 256

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
async def _isolated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[None]:
    """Empty the database and redirect uploads into a temp directory."""
    async with engine.begin() as conn:
        await conn.execute(
            text(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE;")
        )

    # The storage root comes from a cached Settings instance, so both caches have
    # to go: the settings (to pick up the new path) and the storage service (to
    # rebuild itself against it).
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    get_settings.cache_clear()
    reset_storage_service()

    yield

    get_settings.cache_clear()
    reset_storage_service()
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


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def register(client: AsyncClient) -> dict:
    email = f"user-{uuid.uuid4().hex[:12]}@example.com"
    response = await client.post(
        "/auth/signup",
        json={"email": email, "password": "Str0ngPassw0rd!", "full_name": "Asha Rao"},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def upload(
    client: AsyncClient, token: str, data: bytes = PNG, filename: str = "rx.png"
) -> dict:
    response = await client.post(
        "/prescriptions/upload",
        headers=auth(token),
        files={"file": (filename, data, "image/png")},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def mock_ocr(client: AsyncClient, token: str, prescription_id: int) -> dict:
    response = await client.post(
        f"/prescriptions/{prescription_id}/mock-ocr", headers=auth(token)
    )
    assert response.status_code == 201, response.text
    return response.json()


# --------------------------------------------------------------------------
# auth is required
# --------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/prescriptions/upload"),
        ("get", "/prescriptions"),
        ("get", "/prescriptions/1"),
        ("delete", "/prescriptions/1"),
        ("post", "/prescriptions/1/ocr-results"),
        ("post", "/prescriptions/1/mock-ocr"),
        ("get", "/medicines"),
        ("get", "/medicines/pending-review"),
        ("get", "/medicines/duplicates"),
        ("post", "/medicines"),
        ("patch", "/medicines/1/confirm"),
        ("patch", "/medicines/1/reject"),
        ("patch", "/medicines/duplicates/1/resolve"),
    ],
)
async def test_every_route_requires_authentication(
    client: AsyncClient, method: str, path: str
) -> None:
    """Nothing in the prescription or medicine surface is reachable anonymously."""
    response = await client.request(
        method.upper(), path, json={} if method in {"post", "patch"} else None
    )
    assert (
        response.status_code == 401
    ), f"{method.upper()} {path} -> {response.status_code}"


# --------------------------------------------------------------------------
# upload
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_stores_the_file_and_registers_the_prescription(
    client: AsyncClient, session
) -> None:
    token = (await register(client))["access_token"]

    body = await upload(client, token)

    assert body["file_type"] == "image"
    assert body["file_url"].startswith("/files/prescriptions/")
    assert body["uploaded_at"]
    assert body["source_type"] == "prescription"
    assert body["medicine_count"] == 0
    assert body["pending_review_count"] == 0

    row = await session.scalar(select(Prescription))
    assert row is not None
    assert row.file_url == body["file_url"]
    # The key is what makes deletion possible without parsing the URL.
    assert row.storage_key == row.file_url.removeprefix("/files/")

    # And the bytes really are on disk.
    stored = get_settings().storage_root / row.storage_key
    assert stored.is_file()
    assert stored.read_bytes() == PNG


@pytest.mark.asyncio
async def test_upload_accepts_a_pdf(client: AsyncClient) -> None:
    token = (await register(client))["access_token"]
    response = await client.post(
        "/prescriptions/upload",
        headers=auth(token),
        files={"file": ("rx.pdf", PDF, "application/pdf")},
    )
    assert response.status_code == 201
    assert response.json()["file_type"] == "pdf"


@pytest.mark.asyncio
async def test_upload_rejects_content_that_is_not_an_image_or_pdf(
    client: AsyncClient,
) -> None:
    """A script renamed to .png must not be stored.

    The declared Content-Type is image/png here, which is the point: it is
    client-supplied and must not decide what gets written.
    """
    token = (await register(client))["access_token"]
    response = await client.post(
        "/prescriptions/upload",
        headers=auth(token),
        files={"file": ("harmless.png", b"#!/bin/sh\necho pwned\n", "image/png")},
    )
    assert response.status_code == 415
    assert "unsupported file type" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_upload_rejects_an_oversized_file(client: AsyncClient, session) -> None:
    """The cap is enforced while reading, not against the Content-Length header."""
    token = (await register(client))["access_token"]
    oversized = PNG + b"\x00" * (10 * 1024 * 1024 + 1)

    response = await client.post(
        "/prescriptions/upload",
        headers=auth(token),
        files={"file": ("big.png", oversized, "image/png")},
    )
    assert response.status_code == 413
    # Nothing was written.
    assert await session.scalar(select(Prescription)) is None


@pytest.mark.asyncio
async def test_upload_ignores_the_client_filename(client: AsyncClient, session) -> None:
    """A traversal attempt in the filename cannot escape the upload directory.

    The stored name is generated from a uuid4, so the client's name is not even
    consulted.
    """
    token = (await register(client))["access_token"]
    body = await upload(client, token, filename="../../../app/main.py")

    assert ".." not in body["file_url"]
    row = await session.scalar(select(Prescription))
    assert row is not None
    assert "main.py" not in row.storage_key


@pytest.mark.asyncio
async def test_two_uploads_get_distinct_files(client: AsyncClient) -> None:
    token = (await register(client))["access_token"]
    first = await upload(client, token)
    second = await upload(client, token)
    assert first["file_url"] != second["file_url"]


# --------------------------------------------------------------------------
# listing and retrieval
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_returns_only_the_callers_uploads(client: AsyncClient) -> None:
    mine = (await register(client))["access_token"]
    theirs = (await register(client))["access_token"]

    await upload(client, mine)
    await upload(client, mine)
    await upload(client, theirs)

    body = (await client.get("/prescriptions", headers=auth(mine))).json()
    assert body["total"] == 2
    assert len(body["items"]) == 2

    other = (await client.get("/prescriptions", headers=auth(theirs))).json()
    assert other["total"] == 1


@pytest.mark.asyncio
async def test_detail_is_404_for_another_users_prescription(
    client: AsyncClient,
) -> None:
    """404, not 403 -- a 403 would confirm the id exists."""
    owner = (await register(client))["access_token"]
    stranger = (await register(client))["access_token"]
    body = await upload(client, owner)

    response = await client.get(f"/prescriptions/{body['id']}", headers=auth(stranger))
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_reports_pending_review_counts(client: AsyncClient) -> None:
    token = (await register(client))["access_token"]
    prescription = await upload(client, token)
    await mock_ocr(client, token, prescription["id"])

    body = (await client.get("/prescriptions", headers=auth(token))).json()
    assert body["items"][0]["medicine_count"] == 3
    assert body["items"][0]["pending_review_count"] == 3


@pytest.mark.asyncio
async def test_list_paginates(client: AsyncClient) -> None:
    token = (await register(client))["access_token"]
    for _ in range(3):
        await upload(client, token)

    page = (
        await client.get("/prescriptions?limit=2&offset=0", headers=auth(token))
    ).json()
    assert page["total"] == 3
    assert len(page["items"]) == 2

    tail = (
        await client.get("/prescriptions?limit=2&offset=2", headers=auth(token))
    ).json()
    assert len(tail["items"]) == 1


# --------------------------------------------------------------------------
# OCR ingestion
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mock_ocr_creates_unconfirmed_medicines(client: AsyncClient) -> None:
    token = (await register(client))["access_token"]
    prescription = await upload(client, token)

    body = await mock_ocr(client, token, prescription["id"])

    assert len(body["medicines"]) == 3
    assert body["pending_review_count"] == 3
    for medicine in body["medicines"]:
        assert medicine["is_confirmed"] is False
        assert medicine["status"] == "active"
        # Normalisation waits for a human. Guessing now would put an unverified
        # ingredient in front of a safety check.
        assert medicine["normalized_ingredient"] is None
    # Provenance is reported on /medicines; the nested detail view stays compact.
    assert all(
        m["source"] == "prescription"
        for m in (await client.get("/medicines", headers=auth(token))).json()
    )


@pytest.mark.asyncio
async def test_ocr_results_endpoint_accepts_a_real_payload(client: AsyncClient) -> None:
    token = (await register(client))["access_token"]
    prescription = await upload(client, token)

    response = await client.post(
        f"/prescriptions/{prescription['id']}/ocr-results",
        headers=auth(token),
        json={
            "extractor": "google-vision",
            "medicines": [
                {"raw_name": "Crocin 500mg", "strength": "500mg", "confidence": 0.93},
                {"raw_name": "Restyl 0.5", "dose": "1 tab", "frequency": "at night"},
            ],
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert len(body["medicines"]) == 2
    assert body["medicines"][0]["confidence_score"] == 0.93


@pytest.mark.asyncio
async def test_ocr_results_rejects_an_empty_batch(client: AsyncClient) -> None:
    token = (await register(client))["access_token"]
    prescription = await upload(client, token)

    response = await client.post(
        f"/prescriptions/{prescription['id']}/ocr-results",
        headers=auth(token),
        json={"medicines": []},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_reingesting_does_not_overwrite_earlier_rows(
    client: AsyncClient, session
) -> None:
    """A second OCR pass must not discard a confirmation the user already made.

    This is the reason ingestion only ever inserts.
    """
    token = (await register(client))["access_token"]
    prescription = await upload(client, token)
    await mock_ocr(client, token, prescription["id"])

    first = (await client.get("/medicines/pending-review", headers=auth(token))).json()
    target = first[0]["id"]
    confirmed = await client.patch(
        f"/medicines/{target}/confirm",
        headers=auth(token),
        json={"raw_name": "Crocin 650mg", "strength": "650mg"},
    )
    assert confirmed.status_code == 200

    await mock_ocr(client, token, prescription["id"])

    rows = (await session.scalars(select(Medicine).where(Medicine.id == target))).all()
    assert len(rows) == 1
    assert rows[0].is_confirmed is True
    assert rows[0].raw_name == "Crocin 650mg"


@pytest.mark.asyncio
async def test_pending_review_returns_proposals_oldest_first(
    client: AsyncClient,
) -> None:
    token = (await register(client))["access_token"]
    prescription = await upload(client, token)
    await mock_ocr(client, token, prescription["id"])

    body = (await client.get("/medicines/pending-review", headers=auth(token))).json()
    assert [m["raw_name"] for m in body] == [
        "Crocin 500mg",
        "Dolo 650",
        "Herbal Liver Tonic",
    ]


# --------------------------------------------------------------------------
# confirmation
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirming_normalises_and_clears_the_confidence(
    client: AsyncClient, session
) -> None:
    token = (await register(client))["access_token"]
    prescription = await upload(client, token)
    await mock_ocr(client, token, prescription["id"])

    pending = (
        await client.get("/medicines/pending-review", headers=auth(token))
    ).json()
    target = next(m for m in pending if m["raw_name"] == "Crocin 500mg")

    response = await client.patch(
        f"/medicines/{target['id']}/confirm",
        headers=auth(token),
        json={"raw_name": "Crocin 500mg"},
    )
    assert response.status_code == 200
    body = response.json()

    assert body["is_confirmed"] is True
    assert body["normalized_ingredient"] == "Paracetamol"
    # The extractor's uncertainty is no longer the operative fact.
    assert body["confidence_score"] is None


@pytest.mark.asyncio
async def test_confirming_applies_only_the_supplied_edits(client: AsyncClient) -> None:
    """Correcting one field must not blank the fields OCR got right."""
    token = (await register(client))["access_token"]
    prescription = await upload(client, token)
    await mock_ocr(client, token, prescription["id"])

    pending = (
        await client.get("/medicines/pending-review", headers=auth(token))
    ).json()
    target = next(m for m in pending if m["raw_name"] == "Crocin 500mg")

    body = (
        await client.patch(
            f"/medicines/{target['id']}/confirm",
            headers=auth(token),
            json={"strength": "650mg"},
        )
    ).json()

    assert body["strength"] == "650mg"
    assert body["dose"] == "1 tablet"  # untouched
    assert body["frequency"] == "twice daily"  # untouched
    assert body["duration"] == "5 days"  # untouched


@pytest.mark.asyncio
async def test_confirming_with_an_empty_body_is_rejected(client: AsyncClient) -> None:
    """A mis-wired Confirm button must not push unreviewed values through."""
    token = (await register(client))["access_token"]
    prescription = await upload(client, token)
    await mock_ocr(client, token, prescription["id"])
    target = (
        await client.get("/medicines/pending-review", headers=auth(token))
    ).json()[0]

    response = await client.patch(
        f"/medicines/{target['id']}/confirm", headers=auth(token), json={}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_confirmed_row_leaves_the_review_queue(client: AsyncClient) -> None:
    token = (await register(client))["access_token"]
    prescription = await upload(client, token)
    await mock_ocr(client, token, prescription["id"])

    pending = (
        await client.get("/medicines/pending-review", headers=auth(token))
    ).json()
    await client.patch(
        f"/medicines/{pending[0]['id']}/confirm",
        headers=auth(token),
        json={"raw_name": pending[0]["raw_name"]},
    )

    remaining = (
        await client.get("/medicines/pending-review", headers=auth(token))
    ).json()
    assert len(remaining) == 2


@pytest.mark.asyncio
async def test_unmatched_drug_confirms_without_an_ingredient(
    client: AsyncClient,
) -> None:
    """No mapping is a normal outcome, not an error.

    Forcing a guess would either invent a wrong ingredient or block the user
    from recording a drug the seed table has never heard of.
    """
    token = (await register(client))["access_token"]
    prescription = await upload(client, token)
    await mock_ocr(client, token, prescription["id"])

    pending = (
        await client.get("/medicines/pending-review", headers=auth(token))
    ).json()
    tonic = next(m for m in pending if m["raw_name"] == "Herbal Liver Tonic")

    body = (
        await client.patch(
            f"/medicines/{tonic['id']}/confirm",
            headers=auth(token),
            json={"raw_name": "Herbal Liver Tonic"},
        )
    ).json()

    assert body["is_confirmed"] is True
    assert body["normalized_ingredient"] is None


@pytest.mark.asyncio
async def test_cannot_confirm_another_users_medicine(client: AsyncClient) -> None:
    owner = (await register(client))["access_token"]
    stranger = (await register(client))["access_token"]
    prescription = await upload(client, owner)
    await mock_ocr(client, owner, prescription["id"])
    target = (
        await client.get("/medicines/pending-review", headers=auth(owner))
    ).json()[0]

    response = await client.patch(
        f"/medicines/{target['id']}/confirm",
        headers=auth(stranger),
        json={"raw_name": "Crocin 500mg"},
    )
    assert response.status_code == 404


# --------------------------------------------------------------------------
# rejection
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rejecting_hides_the_row_from_the_list(client: AsyncClient) -> None:
    token = (await register(client))["access_token"]
    prescription = await upload(client, token)
    await mock_ocr(client, token, prescription["id"])

    target = (
        await client.get("/medicines/pending-review", headers=auth(token))
    ).json()[0]
    body = (
        await client.patch(
            f"/medicines/{target['id']}/reject",
            headers=auth(token),
            json={"reason": "this is a supplement, not a prescription item"},
        )
    ).json()

    assert body["status"] == "rejected"
    assert body["is_confirmed"] is False

    remaining = (
        await client.get("/medicines/pending-review", headers=auth(token))
    ).json()
    assert target["id"] not in [m["id"] for m in remaining]

    confirmed = (
        await client.get("/medicines?confirmed=true", headers=auth(token))
    ).json()
    assert target["id"] not in [m["id"] for m in confirmed]


@pytest.mark.asyncio
async def test_rejected_line_keeps_its_row_for_provenance(
    client: AsyncClient, session
) -> None:
    """Rejection marks rather than deletes, so the proposal's history survives."""
    token = (await register(client))["access_token"]
    prescription = await upload(client, token)
    await mock_ocr(client, token, prescription["id"])
    target = (
        await client.get("/medicines/pending-review", headers=auth(token))
    ).json()[0]

    await client.patch(
        f"/medicines/{target['id']}/reject", headers=auth(token), json={"reason": "no"}
    )

    row = await session.scalar(select(Medicine).where(Medicine.id == target["id"]))
    assert row is not None
    assert row.status is MedicineStatus.REJECTED
    assert row.deleted_at is None


@pytest.mark.asyncio
async def test_rejected_line_cannot_be_confirmed(client: AsyncClient) -> None:
    token = (await register(client))["access_token"]
    prescription = await upload(client, token)
    await mock_ocr(client, token, prescription["id"])
    target = (
        await client.get("/medicines/pending-review", headers=auth(token))
    ).json()[0]

    await client.patch(
        f"/medicines/{target['id']}/reject", headers=auth(token), json={}
    )
    response = await client.patch(
        f"/medicines/{target['id']}/confirm",
        headers=auth(token),
        json={"raw_name": "Crocin 500mg"},
    )
    assert response.status_code == 409


# --------------------------------------------------------------------------
# manual entry
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_manual_entry_is_confirmed_and_normalised(client: AsyncClient) -> None:
    token = (await register(client))["access_token"]

    response = await client.post(
        "/medicines",
        headers=auth(token),
        json={"raw_name": "Dolo 650", "strength": "650mg", "frequency": "as needed"},
    )
    assert response.status_code == 201
    body = response.json()

    assert body["is_confirmed"] is True
    assert body["normalized_ingredient"] == "Paracetamol"
    assert body["source"] == "self_reported"
    assert body["confidence_score"] is None


@pytest.mark.asyncio
async def test_manual_entry_rejects_the_rejected_status(client: AsyncClient) -> None:
    """A rejected row is produced by rejecting an extraction, not by typing one."""
    token = (await register(client))["access_token"]
    response = await client.post(
        "/medicines",
        headers=auth(token),
        json={"raw_name": "Dolo 650", "status": "rejected"},
    )
    assert response.status_code == 422


# --------------------------------------------------------------------------
# duplicate detection and resolution
# --------------------------------------------------------------------------


async def confirm_named(
    client: AsyncClient, token: str, raw_name: str, edits: dict | None = None
) -> dict:
    """Confirm one pending proposal, by its raw name."""
    pending = (
        await client.get("/medicines/pending-review", headers=auth(token))
    ).json()
    target = next(m for m in pending if m["raw_name"] == raw_name)
    response = await client.patch(
        f"/medicines/{target['id']}/confirm",
        headers=auth(token),
        json=edits or {"raw_name": raw_name},
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_two_brands_of_one_ingredient_are_flagged(client: AsyncClient) -> None:
    """The reconciliation requirement, end to end.

    Crocin and Dolo are different products and the same active ingredient, and
    confirming the second must raise a flag the user can see and resolve.
    """
    token = (await register(client))["access_token"]
    prescription = await upload(client, token)
    await mock_ocr(client, token, prescription["id"])

    first = await confirm_named(client, token, "Crocin 500mg")
    assert first["normalized_ingredient"] == "Paracetamol"

    # No duplicate yet -- there is nothing to duplicate.
    assert (await client.get("/medicines/duplicates", headers=auth(token))).json() == []

    second = await confirm_named(client, token, "Dolo 650")
    assert second["normalized_ingredient"] == "Paracetamol"

    flags = (await client.get("/medicines/duplicates", headers=auth(token))).json()
    assert len(flags) == 1
    pair = {flags[0]["medicine_a"]["id"], flags[0]["medicine_b"]["id"]}
    assert pair == {first["id"], second["id"]}
    assert flags[0]["resolved"] is False
    assert flags[0]["resolved_at"] is None


@pytest.mark.asyncio
async def test_no_flag_for_a_single_ingredient(client: AsyncClient) -> None:
    """Different drugs must not be flagged against each other."""
    token = (await register(client))["access_token"]
    prescription = await upload(client, token)
    await mock_ocr(client, token, prescription["id"])

    await confirm_named(client, token, "Crocin 500mg")
    await confirm_named(client, token, "Herbal Liver Tonic")

    assert (await client.get("/medicines/duplicates", headers=auth(token))).json() == []


@pytest.mark.asyncio
async def test_unconfirmed_rows_are_not_compared(client: AsyncClient) -> None:
    """A proposal is not a drug, so it must not generate a duplicate."""
    token = (await register(client))["access_token"]
    prescription = await upload(client, token)
    await mock_ocr(client, token, prescription["id"])

    await confirm_named(client, token, "Crocin 500mg")
    # 'Dolo 650' is still an unconfirmed proposal at this point.
    assert (await client.get("/medicines/duplicates", headers=auth(token))).json() == []


@pytest.mark.asyncio
async def test_manual_entry_duplicates_a_prescription_medicine(
    client: AsyncClient,
) -> None:
    """Cross-source detection: a typed 'Dolo 650' collides with an uploaded 'Crocin'."""
    token = (await register(client))["access_token"]
    prescription = await upload(client, token)
    await mock_ocr(client, token, prescription["id"])
    await confirm_named(client, token, "Crocin 500mg")

    response = await client.post(
        "/medicines",
        headers=auth(token),
        json={"raw_name": "Dolo 650", "strength": "650mg"},
    )
    assert response.status_code == 201

    flags = (await client.get("/medicines/duplicates", headers=auth(token))).json()
    assert len(flags) == 1


@pytest.mark.asyncio
async def test_duplicates_are_private_to_their_owner(client: AsyncClient) -> None:
    owner = (await register(client))["access_token"]
    stranger = (await register(client))["access_token"]
    prescription = await upload(client, owner)
    await mock_ocr(client, owner, prescription["id"])
    await confirm_named(client, owner, "Crocin 500mg")
    await confirm_named(client, owner, "Dolo 650")

    assert (
        len((await client.get("/medicines/duplicates", headers=auth(owner))).json())
        == 1
    )
    # The flag table has no user_id; ownership comes from the medicines.
    assert (
        await client.get("/medicines/duplicates", headers=auth(stranger))
    ).json() == []


@pytest.mark.asyncio
async def test_resolving_as_keep_both_hides_the_flag(
    client: AsyncClient, session
) -> None:
    token = (await register(client))["access_token"]
    prescription = await upload(client, token)
    await mock_ocr(client, token, prescription["id"])
    await confirm_named(client, token, "Crocin 500mg")
    await confirm_named(client, token, "Dolo 650")

    flag = (await client.get("/medicines/duplicates", headers=auth(token))).json()[0]

    response = await client.patch(
        f"/medicines/duplicates/{flag['id']}/resolve",
        headers=auth(token),
        json={
            "resolution": "keep_both",
            "note": "different strengths, both prescribed",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["resolved"] is True
    assert body["resolved_at"]
    assert body["removed_medicine_id"] is None

    # Neither medicine is touched, and the flag leaves the open list.
    assert (await client.get("/medicines/duplicates", headers=auth(token))).json() == []
    medicines = (await client.get("/medicines", headers=auth(token))).json()
    assert len([m for m in medicines if m["is_confirmed"]]) == 2

    # It is still retrievable as history.
    history = (
        await client.get(
            "/medicines/duplicates?include_resolved=true", headers=auth(token)
        )
    ).json()
    assert len(history) == 1


@pytest.mark.asyncio
async def test_resolving_as_merged_tombstones_the_other_row(
    client: AsyncClient, session
) -> None:
    token = (await register(client))["access_token"]
    prescription = await upload(client, token)
    await mock_ocr(client, token, prescription["id"])
    keeper = await confirm_named(client, token, "Crocin 500mg")
    await confirm_named(client, token, "Dolo 650")

    flag = (await client.get("/medicines/duplicates", headers=auth(token))).json()[0]

    body = (
        await client.patch(
            f"/medicines/duplicates/{flag['id']}/resolve",
            headers=auth(token),
            json={"resolution": "merged", "kept_medicine_id": keeper["id"]},
        )
    ).json()

    assert body["removed_medicine_id"] not in (None, keeper["id"])
    assert body["kept_medicine_id"] == keeper["id"]

    # The loser is hidden, and the winner keeps its own data -- nothing is
    # copied between the two, because which strength to keep is the user's call.
    listed = (await client.get("/medicines?confirmed=true", headers=auth(token))).json()
    assert [m["id"] for m in listed] == [keeper["id"]]
    assert listed[0]["strength"] == keeper["strength"]

    with include_deleted():
        loser = await session.scalar(
            select(Medicine).where(Medicine.id == body["removed_medicine_id"])
        )
    assert loser is not None and loser.deleted_at is not None


@pytest.mark.asyncio
async def test_merged_requires_a_survivor(client: AsyncClient) -> None:
    token = (await register(client))["access_token"]
    prescription = await upload(client, token)
    await mock_ocr(client, token, prescription["id"])
    await confirm_named(client, token, "Crocin 500mg")
    await confirm_named(client, token, "Dolo 650")
    flag = (await client.get("/medicines/duplicates", headers=auth(token))).json()[0]

    response = await client.patch(
        f"/medicines/duplicates/{flag['id']}/resolve",
        headers=auth(token),
        json={"resolution": "merged"},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_merged_rejects_a_medicine_outside_the_pair(client: AsyncClient) -> None:
    token = (await register(client))["access_token"]
    prescription = await upload(client, token)
    await mock_ocr(client, token, prescription["id"])
    await confirm_named(client, token, "Crocin 500mg")
    await confirm_named(client, token, "Dolo 650")
    unrelated = (
        await client.post(
            "/medicines", headers=auth(token), json={"raw_name": "Restyl 0.5"}
        )
    ).json()
    flag = (await client.get("/medicines/duplicates", headers=auth(token))).json()[0]

    response = await client.patch(
        f"/medicines/duplicates/{flag['id']}/resolve",
        headers=auth(token),
        json={"resolution": "merged", "kept_medicine_id": unrelated["id"]},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_resolving_twice_is_a_conflict(client: AsyncClient) -> None:
    token = (await register(client))["access_token"]
    prescription = await upload(client, token)
    await mock_ocr(client, token, prescription["id"])
    await confirm_named(client, token, "Crocin 500mg")
    await confirm_named(client, token, "Dolo 650")
    flag = (await client.get("/medicines/duplicates", headers=auth(token))).json()[0]

    payload = {"resolution": "keep_both"}
    first = await client.patch(
        f"/medicines/duplicates/{flag['id']}/resolve", headers=auth(token), json=payload
    )
    assert first.status_code == 200
    second = await client.patch(
        f"/medicines/duplicates/{flag['id']}/resolve", headers=auth(token), json=payload
    )
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_cannot_resolve_another_users_flag(client: AsyncClient) -> None:
    owner = (await register(client))["access_token"]
    stranger = (await register(client))["access_token"]
    prescription = await upload(client, owner)
    await mock_ocr(client, owner, prescription["id"])
    await confirm_named(client, owner, "Crocin 500mg")
    await confirm_named(client, owner, "Dolo 650")
    flag = (await client.get("/medicines/duplicates", headers=auth(owner))).json()[0]

    response = await client.patch(
        f"/medicines/duplicates/{flag['id']}/resolve",
        headers=auth(stranger),
        json={"resolution": "keep_both"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_unknown_duplicate_id_is_404(client: AsyncClient) -> None:
    token = (await register(client))["access_token"]
    response = await client.patch(
        "/medicines/duplicates/9999/resolve",
        headers=auth(token),
        json={"resolution": "keep_both"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_reconfirming_a_medicine_does_not_duplicate_the_flag(
    client: AsyncClient,
) -> None:
    """The invariant: one flag per pair, however many times it is re-evaluated.

    Detection runs on every confirmation, so editing and re-confirming one side
    of a known duplicate walks the same pair again. The unique constraint would
    catch a duplicate insert as an error; the existence check catches it first
    and turns it into a no-op, which is the difference between a re-confirmation
    working and 500ing.
    """
    token = (await register(client))["access_token"]
    prescription = await upload(client, token)
    await mock_ocr(client, token, prescription["id"])

    first = await confirm_named(client, token, "Crocin 500mg")
    second = await confirm_named(client, token, "Dolo 650")

    flags = (await client.get("/medicines/duplicates", headers=auth(token))).json()
    assert len(flags) == 1
    original_id = flags[0]["id"]

    # Correct the first one's name and confirm it again.
    reconfirmed = (
        await client.patch(
            f"/medicines/{first['id']}/confirm",
            headers=auth(token),
            json={"raw_name": "Crocin 650mg", "strength": "650mg"},
        )
    ).json()
    assert reconfirmed["id"] == first["id"]
    assert reconfirmed["normalized_ingredient"] == "Paracetamol"

    # Still exactly one flag, and it is the same one.
    after = (await client.get("/medicines/duplicates", headers=auth(token))).json()
    assert len(after) == 1
    assert after[0]["id"] == original_id
    pair = {after[0]["medicine_a"]["id"], after[0]["medicine_b"]["id"]}
    assert pair == {first["id"], second["id"]}


@pytest.mark.asyncio
async def test_a_resolved_pair_is_not_reopened_by_another_upload(
    client: AsyncClient,
) -> None:
    """A dismissal settles the question, not just the current flag.

    Re-uploading the same document creates new medicine rows and therefore new
    pairs; each of those is legitimately its own flag. What must not happen is
    the *same* pair being raised a second time after the user answered it.
    """
    token = (await register(client))["access_token"]
    prescription = await upload(client, token)
    await mock_ocr(client, token, prescription["id"])
    await confirm_named(client, token, "Crocin 500mg")
    await confirm_named(client, token, "Dolo 650")

    flag = (await client.get("/medicines/duplicates", headers=auth(token))).json()[0]
    await client.patch(
        f"/medicines/duplicates/{flag['id']}/resolve",
        headers=auth(token),
        json={"resolution": "keep_both"},
    )

    # Re-confirming either original medicine must not resurrect the flag.
    for medicine_id in (flag["medicine_a"]["id"], flag["medicine_b"]["id"]):
        await client.patch(
            f"/medicines/{medicine_id}/confirm",
            headers=auth(token),
            json={"raw_name": flag["medicine_a"]["raw_name"]},
        )

    assert (await client.get("/medicines/duplicates", headers=auth(token))).json() == []
    history = (
        await client.get(
            "/medicines/duplicates?include_resolved=true", headers=auth(token)
        )
    ).json()
    assert len(history) == 1
    assert history[0]["resolved"] is True


# --------------------------------------------------------------------------
# medicine listing
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_medicine_list_can_be_filtered_by_confirmation(
    client: AsyncClient,
) -> None:
    token = (await register(client))["access_token"]
    prescription = await upload(client, token)
    await mock_ocr(client, token, prescription["id"])
    await confirm_named(client, token, "Crocin 500mg")

    everything = (await client.get("/medicines", headers=auth(token))).json()
    confirmed = (
        await client.get("/medicines?confirmed=true", headers=auth(token))
    ).json()
    pending = (
        await client.get("/medicines?confirmed=false", headers=auth(token))
    ).json()

    assert len(everything) == 3
    assert len(confirmed) == 1
    assert confirmed[0]["normalized_ingredient"] == "Paracetamol"
    assert len(pending) == 2


@pytest.mark.asyncio
async def test_medicine_list_filters_by_status(client: AsyncClient) -> None:
    token = (await register(client))["access_token"]
    prescription = await upload(client, token)
    await mock_ocr(client, token, prescription["id"])
    target = (
        await client.get("/medicines/pending-review", headers=auth(token))
    ).json()[0]
    await client.patch(
        f"/medicines/{target['id']}/reject", headers=auth(token), json={}
    )

    rejected = (
        await client.get("/medicines?status=rejected", headers=auth(token))
    ).json()
    assert [m["id"] for m in rejected] == [target["id"]]


@pytest.mark.asyncio
async def test_medicine_list_excludes_deleted_rows(
    client: AsyncClient, session
) -> None:
    """A tombstoned row must not come back through an ordinary read."""
    token = (await register(client))["access_token"]
    created = (
        await client.post(
            "/medicines", headers=auth(token), json={"raw_name": "Restyl 0.5"}
        )
    ).json()

    # Soft-delete it the way a merge would.
    with include_deleted():
        row = await session.scalar(select(Medicine).where(Medicine.id == created["id"]))
        assert row is not None
        row.deleted_at = datetime.now(UTC)
        await session.commit()

    assert (await client.get("/medicines", headers=auth(token))).json() == []


# --------------------------------------------------------------------------
# deletion
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_removes_the_row_and_the_file(
    client: AsyncClient, session
) -> None:
    token = (await register(client))["access_token"]
    prescription = await upload(client, token)
    stored = get_settings().storage_root / (
        await session.scalar(select(Prescription.storage_key))
    )
    assert stored.is_file()

    response = await client.delete(
        f"/prescriptions/{prescription['id']}", headers=auth(token)
    )
    assert response.status_code == 200

    assert not stored.exists()
    assert (await client.get("/prescriptions", headers=auth(token))).json()[
        "total"
    ] == 0
    assert (
        await client.get(f"/prescriptions/{prescription['id']}", headers=auth(token))
    ).status_code == 404

    # The row is tombstoned, not destroyed: retention still applies.
    with include_deleted():
        row = await session.scalar(
            select(Prescription).where(Prescription.id == prescription["id"])
        )
    assert row is not None and row.deleted_at is not None


@pytest.mark.asyncio
async def test_delete_tombstones_the_extracted_medicines(
    client: AsyncClient, session
) -> None:
    """Cascading to medicines is the point: a deleted upload leaves nothing live."""
    token = (await register(client))["access_token"]
    prescription = await upload(client, token)
    await mock_ocr(client, token, prescription["id"])
    assert len((await client.get("/medicines", headers=auth(token))).json()) == 3

    await client.delete(f"/prescriptions/{prescription['id']}", headers=auth(token))

    assert (await client.get("/medicines", headers=auth(token))).json() == []
    assert (
        await client.get("/medicines/pending-review", headers=auth(token))
    ).json() == []


@pytest.mark.asyncio
async def test_delete_keeps_medicines_added_by_hand(client: AsyncClient) -> None:
    """Only the upload's own rows are cascaded.

    A medicine the user typed is theirs, not the document's, so deleting an
    upload must not take it with them.
    """
    token = (await register(client))["access_token"]
    prescription = await upload(client, token)
    await mock_ocr(client, token, prescription["id"])
    manual = (
        await client.post(
            "/medicines", headers=auth(token), json={"raw_name": "Restyl 0.5"}
        )
    ).json()

    await client.delete(f"/prescriptions/{prescription['id']}", headers=auth(token))

    listed = (await client.get("/medicines", headers=auth(token))).json()
    assert [m["id"] for m in listed] == [manual["id"]]


@pytest.mark.asyncio
async def test_cannot_delete_another_users_prescription(client: AsyncClient) -> None:
    owner = (await register(client))["access_token"]
    stranger = (await register(client))["access_token"]
    prescription = await upload(client, owner)

    response = await client.delete(
        f"/prescriptions/{prescription['id']}", headers=auth(stranger)
    )
    assert response.status_code == 404
    # Still there for its owner.
    assert (await client.get("/prescriptions", headers=auth(owner))).json()[
        "total"
    ] == 1


@pytest.mark.asyncio
async def test_delete_unknown_prescription_is_404(client: AsyncClient) -> None:
    token = (await register(client))["access_token"]
    response = await client.delete("/prescriptions/4242", headers=auth(token))
    assert response.status_code == 404


# --------------------------------------------------------------------------
# soft deletion of the whole account
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_account_deletion_hides_prescriptions_and_medicines(
    client: AsyncClient, session
) -> None:
    """The pre-existing erasure guarantee has to extend to the new tables.

    Prescriptions and medicines were in the soft-delete set from the start of
    this feature; this asserts the cascade actually reaches them now that they
    hold real data.
    """
    token = (await register(client))["access_token"]
    prescription = await upload(client, token)
    await mock_ocr(client, token, prescription["id"])
    await confirm_named(client, token, "Crocin 500mg")
    await confirm_named(client, token, "Dolo 650")

    user_id = await session.scalar(select(Prescription.user_id))
    assert (await client.get("/medicines/duplicates", headers=auth(token))).json()

    deleted = await client.delete("/users/me", headers=auth(token))
    assert deleted.status_code == 200

    # The token stops working entirely.
    assert (await client.get("/medicines", headers=auth(token))).status_code == 401

    with include_deleted():
        prescriptions = (
            await session.scalars(
                select(Prescription).where(Prescription.user_id == user_id)
            )
        ).all()
        medicines = (
            await session.scalars(select(Medicine).where(Medicine.user_id == user_id))
        ).all()
        flags = (
            await session.scalars(
                select(DuplicateFlag).where(DuplicateFlag.medicine_id_a > 0)
            )
        ).all()

    assert prescriptions and all(p.deleted_at is not None for p in prescriptions)
    assert medicines and all(m.deleted_at is not None for m in medicines)
    assert all(f.deleted_at is not None for f in flags)


# --------------------------------------------------------------------------
# audit trail
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_whole_flow_is_audited(client: AsyncClient, session) -> None:
    """Every state change in the flow leaves a trace, per the brief."""
    token = (await register(client))["access_token"]
    prescription = await upload(client, token)
    await mock_ocr(client, token, prescription["id"])
    await confirm_named(client, token, "Crocin 500mg")

    # Dismiss the unrecognised tonic, leaving the Paracetamol pair intact.
    await confirm_named(client, token, "Herbal Liver Tonic")
    tonic = (await client.get("/medicines?confirmed=true", headers=auth(token))).json()
    tonic = next(m for m in tonic if m["normalized_ingredient"] is None)
    rejected = await client.patch(
        f"/medicines/{tonic['id']}/reject",
        headers=auth(token),
        json={"reason": "supplement"},
    )
    assert rejected.status_code == 200

    await confirm_named(client, token, "Dolo 650")
    flag = (await client.get("/medicines/duplicates", headers=auth(token))).json()[0]
    await client.patch(
        f"/medicines/duplicates/{flag['id']}/resolve",
        headers=auth(token),
        json={"resolution": "keep_both"},
    )
    await client.delete(f"/prescriptions/{prescription['id']}", headers=auth(token))

    rows = list((await session.scalars(select(AuditLog.action))).all())
    for expected in (
        "prescription.uploaded",
        "prescription.ocr_results_recorded",
        "medicine.confirmed",
        "medicine.rejected",
        "medicine.duplicate_resolved",
        "prescription.deleted",
    ):
        assert expected in rows, f"missing audit action: {expected}"


@pytest.mark.asyncio
async def test_a_rejected_upload_is_audited_too(client: AsyncClient, session) -> None:
    """A refused upload is exactly the event a security reviewer wants to see."""
    token = (await register(client))["access_token"]
    await client.post(
        "/prescriptions/upload",
        headers=auth(token),
        files={"file": ("x.png", b"not an image", "image/png")},
    )

    actions = list((await session.scalars(select(AuditLog.action))).all())
    assert "prescription.upload_rejected" in actions


@pytest.mark.asyncio
async def test_audit_entries_carry_the_owner_and_ip(
    client: AsyncClient, session
) -> None:
    token = (await register(client))["access_token"]
    body = await upload(client, token)

    entry = await session.scalar(
        select(AuditLog).where(
            AuditLog.action == "prescription.uploaded",
            AuditLog.resource_id == str(body["id"]),
        )
    )
    assert entry is not None
    assert entry.resource_type == "prescription"
    assert entry.user_id is not None
    # The ASGI transport reports the peer as 127.0.0.1, not the httpx client
    # name; what matters is that a real address is captured and fits the column.
    assert entry.ip_address is not None
    assert len(entry.ip_address) <= 45
