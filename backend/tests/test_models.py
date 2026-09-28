"""Model and constraint tests against a live PostgreSQL.

These cover the behaviours that are easy to get wrong and invisible in review:
PostgreSQL enum round-tripping, ON DELETE CASCADE actually firing through the
ORM, and the CHECK/UNIQUE constraints backing them.
"""

from collections.abc import AsyncIterator
from datetime import time

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.database import AsyncSessionLocal, engine
from app.models import (
    AuditLog,
    DuplicateFlag,
    InteractionAlert,
    InteractionSeverity,
    Medicine,
    MedicineStatus,
    Prescription,
    PrescriptionFileType,
    ReminderSchedule,
    User,
    UserContextType,
    UserProfile,
)
from app.models.enums import MedicineSourceType

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def _clean_database() -> AsyncIterator[None]:
    """Empty every table and drop pooled connections around each test.

    The dispose is required, not cosmetic: the engine is a module-level
    singleton and asyncpg connections belong to the event loop that opened
    them, so a connection cached by an earlier test is dead in the next one.
    """
    async with AsyncSessionLocal() as session:
        for model in (
            AuditLog,
            ReminderSchedule,
            DuplicateFlag,
            InteractionAlert,
            Medicine,
            Prescription,
            UserProfile,
            User,
        ):
            await session.execute(model.__table__.delete())
        await session.commit()
    yield
    try:
        await engine.dispose()
    except Exception:
        pass


@pytest.fixture
async def session() -> AsyncIterator:
    async with AsyncSessionLocal() as db:
        yield db


async def _make_user(session, **overrides) -> User:
    values = {
        "email": "test@example.com",
        "hashed_password": "hashed",
        "full_name": "Test User",
    }
    values.update(overrides)
    user = User(**values)
    user.profile = UserProfile(
        context_type=UserContextType.BREASTFEEDING,
        infant_age_months=2,
    )
    session.add(user)
    await session.commit()
    return user


async def test_enum_values_round_trip_as_python_enums(session) -> None:
    """The DB must store the lowercase label, not the Python member name."""
    user = await _make_user(session)
    medicine = Medicine(
        user_id=user.id,
        raw_name="Brufen 400",
        status=MedicineStatus.DISCONTINUED,
    )
    session.add(medicine)
    await session.commit()

    stored = (
        await session.execute(select(Medicine.status).where(Medicine.id == medicine.id))
    ).scalar_one()

    assert stored is MedicineStatus.DISCONTINUED
    assert stored.value == "discontinued"


async def test_server_defaults_apply(session) -> None:
    user = await _make_user(session)
    medicine = Medicine(user_id=user.id, raw_name="Crocin 650")
    session.add(medicine)
    await session.commit()
    await session.refresh(medicine)

    assert medicine.status is MedicineStatus.ACTIVE
    assert medicine.is_confirmed is False
    assert medicine.created_at is not None


async def test_prescription_enum_columns(session) -> None:
    user = await _make_user(session)
    rx = Prescription(
        user_id=user.id,
        file_url="https://example.test/rx.pdf",
        storage_key="prescriptions/1/fixture.pdf",
        file_type=PrescriptionFileType.PDF,
        source_type=MedicineSourceType.OTC,
    )
    session.add(rx)
    await session.commit()
    await session.refresh(rx)

    assert rx.file_type is PrescriptionFileType.PDF
    assert rx.source_type is MedicineSourceType.OTC
    assert rx.uploaded_at is not None


async def test_deleting_user_cascades_without_nulling_foreign_keys(session) -> None:
    """Regression: without passive_deletes the ORM NULLs NOT NULL FKs and
    raises NotNullViolationError instead of letting ON DELETE CASCADE run."""
    user = await _make_user(session)
    prescription = Prescription(
        user_id=user.id,
        file_url="https://example.test/rx.jpg",
        storage_key="prescriptions/1/fixture.jpg",
        file_type=PrescriptionFileType.IMAGE,
        source_type=MedicineSourceType.PRESCRIPTION,
    )
    session.add(prescription)
    await session.commit()

    a = Medicine(user_id=user.id, raw_name="Crocin 650")
    b = Medicine(user_id=user.id, raw_name="Brufen 400")
    session.add_all([a, b])
    await session.commit()

    alert = InteractionAlert(
        user_id=user.id,
        severity=InteractionSeverity.HIGH,
        rationale="Test rationale",
    )
    alert.medicines = [a, b]
    session.add(alert)
    session.add(DuplicateFlag(medicine_id_a=a.id, medicine_id_b=b.id))
    session.add(
        ReminderSchedule(
            user_id=user.id,
            medicine_id=a.id,
            time_of_day=time(8, 0),
            frequency="daily",
        )
    )
    session.add(
        AuditLog(
            user_id=user.id,
            action="test.action",
            resource_type="user",
            resource_id=str(user.id),
        )
    )
    await session.commit()

    await session.delete(user)
    await session.commit()

    for model in (
        User,
        UserProfile,
        Prescription,
        Medicine,
        DuplicateFlag,
        InteractionAlert,
    ):
        remaining = (
            await session.execute(select(func.count()).select_from(model.__table__))
        ).scalar_one()
        assert remaining == 0, f"{model.__tablename__} should have cascaded to 0"

    # audit_logs.user_id is ON DELETE SET NULL: the trail is deliberately kept.
    surviving_logs = (
        await session.execute(select(func.count()).select_from(AuditLog.__table__))
    ).scalar_one()
    assert surviving_logs == 1


async def test_duplicate_flag_rejects_self_reference(session) -> None:
    user = await _make_user(session)
    medicine = Medicine(user_id=user.id, raw_name="Crocin 650")
    session.add(medicine)
    await session.commit()

    session.add(DuplicateFlag(medicine_id_a=medicine.id, medicine_id_b=medicine.id))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


async def test_confidence_score_must_be_a_probability(session) -> None:
    user = await _make_user(session)
    session.add(Medicine(user_id=user.id, raw_name="Bad", confidence_score=1.4))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


async def test_trimester_range_is_enforced(session) -> None:
    user = await _make_user(session)
    user.profile.context_type = UserContextType.PREGNANT
    user.profile.trimester = 4
    session.add(user)
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


async def test_profile_is_one_per_user(session) -> None:
    user = await _make_user(session)
    session.add(UserProfile(user_id=user.id))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()
