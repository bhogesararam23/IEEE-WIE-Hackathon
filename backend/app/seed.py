"""Demo data seed script.

Populates the database with realistic presentation-ready data:
- Demo User 1: Pregnant user (Trimester 2) taking Ciprofloxacin + Moxifloxacin (HIGH severity DDI alert).
- Demo User 2: Breastfeeding user (Infant age 4m) taking Crocin 500mg + Dolo 650 (Duplicate flag) + Disprin 325 (Moderate DDI alert).

Can be executed via `python -m app.seed` or `python seed_demo.py`.
"""

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal, engine
from app.core.security import hash_password
from app.models.enums import (
    InteractionSeverity,
    MedicineSourceType,
    MedicineStatus,
    PrescriptionFileType,
    UserContextType,
)
from app.models.interaction import EvidenceReference, InteractionAlert
from app.models.medicine import DuplicateFlag, Medicine
from app.models.prescription import Prescription
from app.models.reminder import ReminderSchedule
from app.models.user import User, UserProfile
from app.services import reconcile
from app.services.brand_map import normalize_medicine
from app.services.interactions import check_interactions

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app.seed")


async def seed_demo_data(session: AsyncSession) -> None:
    logger.info("Starting demo database seed...")

    # Check if demo users already exist
    existing = await session.scalar(
        select(User).where(User.email == "demo_pregnant@hermedisafe.org")
    )
    if existing:
        logger.info("Demo data already seeded. Skipping creation.")
        return

    # ------------------------------------------------------------------
    # User 1: Pregnant User (High Severity Interaction Demo)
    # ------------------------------------------------------------------
    user1 = User(
        email="demo_pregnant@hermedisafe.org",
        hashed_password=hash_password("DemoUser123!"),
        full_name="Priya Sharma",
        consent_given_at=datetime.now(UTC),
    )
    session.add(user1)
    await session.flush()

    profile1 = UserProfile(
        user_id=user1.id,
        context_type=UserContextType.PREGNANT,
        trimester=2,
    )
    session.add(profile1)

    rx1 = Prescription(
        user_id=user1.id,
        file_url="/files/prescriptions/demo/rx_priya_sharma_2026.png",
        storage_key="prescriptions/demo/rx_priya_sharma_2026.png",
        file_type=PrescriptionFileType.IMAGE,
        source_type=MedicineSourceType.PRESCRIPTION,
    )
    session.add(rx1)
    await session.flush()

    # Confirmed Medicine 1: Ciprofloxacin 500mg
    norm1 = normalize_medicine("Ciprofloxacin 500mg", "500mg")
    med1 = Medicine(
        user_id=user1.id,
        prescription_id=rx1.id,
        raw_name="Ciprofloxacin 500mg",
        brand_name="Ciplox 500",
        normalized_ingredient=norm1.ingredient or "Ciprofloxacin",
        strength="500mg",
        dose="1 tablet",
        frequency="twice daily",
        duration="7 days",
        is_confirmed=True,
        status=MedicineStatus.ACTIVE,
    )
    session.add(med1)

    # Confirmed Medicine 2: Moxifloxacin 400mg
    norm2 = normalize_medicine("Moxifloxacin 400mg", "400mg")
    med2 = Medicine(
        user_id=user1.id,
        prescription_id=rx1.id,
        raw_name="Moxifloxacin 400mg",
        brand_name="Avelox 400",
        normalized_ingredient=norm2.ingredient or "Moxifloxacin",
        strength="400mg",
        dose="1 tablet",
        frequency="once daily",
        duration="5 days",
        is_confirmed=True,
        status=MedicineStatus.ACTIVE,
    )
    session.add(med2)
    await session.flush()

    # Reminder schedule for User 1
    rem1 = ReminderSchedule(
        user_id=user1.id,
        medicine_id=med1.id,
        time_of_day=datetime.strptime("08:00:00", "%H:%M:%S").time(),
        frequency="twice_daily",
        is_active=True,
    )
    session.add(rem1)

    # Trigger interaction check for User 1 (will create HIGH severity Ciprofloxacin + Moxifloxacin alert)
    await session.flush()
    alerts1, _ = await check_interactions(session, user_id=user1.id)
    if alerts1:
        # Add RAG evidence citation to the high-severity alert
        high_alert = alerts1[0]
        high_alert.source_reference = (
            "PubMed ID 2891234: Combining two fluoroquinolone antibiotics "
            "(Ciprofloxacin + Moxifloxacin) produces additive QT interval prolongation and "
            "substantially elevates risk of Torsades de Pointes."
        )
        high_alert.reviewed_by_professional = True
        ref1 = EvidenceReference(
            alert_id=high_alert.id,
            title="Fluoroquinolone Co-Administration & Cardiotoxicity Risk (FDA Drug Safety)",
            url="https://pubmed.ncbi.nlm.nih.gov/2891234/",
        )
        session.add(ref1)

    logger.info("Created Demo User 1 (Pregnant) with HIGH severity interaction alert.")

    # ------------------------------------------------------------------
    # User 2: Breastfeeding User (Duplicate & Moderate DDI Demo)
    # ------------------------------------------------------------------
    user2 = User(
        email="demo_breastfeeding@hermedisafe.org",
        hashed_password=hash_password("DemoUser123!"),
        full_name="Ananya Verma",
        consent_given_at=datetime.now(UTC),
    )
    session.add(user2)
    await session.flush()

    profile2 = UserProfile(
        user_id=user2.id,
        context_type=UserContextType.BREASTFEEDING,
        infant_age_months=4,
    )
    session.add(profile2)

    rx2 = Prescription(
        user_id=user2.id,
        file_url="/files/prescriptions/demo/rx_ananya_2026.png",
        storage_key="prescriptions/demo/rx_ananya_2026.png",
        file_type=PrescriptionFileType.IMAGE,
        source_type=MedicineSourceType.PRESCRIPTION,
    )
    session.add(rx2)
    await session.flush()

    # Confirmed Medicine A: Crocin 500mg (Paracetamol)
    norm3 = normalize_medicine("Crocin 500mg", "500mg")
    med3 = Medicine(
        user_id=user2.id,
        prescription_id=rx2.id,
        raw_name="Crocin 500mg",
        brand_name="Crocin",
        normalized_ingredient=norm3.ingredient or "Paracetamol",
        strength="500mg",
        dose="1 tablet",
        frequency="twice daily",
        duration="5 days",
        is_confirmed=True,
        status=MedicineStatus.ACTIVE,
    )
    session.add(med3)

    # Confirmed Medicine B: Dolo 650 (Paracetamol — triggers duplicate flag with Crocin)
    norm4 = normalize_medicine("Dolo 650", "650mg")
    med4 = Medicine(
        user_id=user2.id,
        prescription_id=rx2.id,
        raw_name="Dolo 650",
        brand_name="Dolo",
        normalized_ingredient=norm4.ingredient or "Paracetamol",
        strength="650mg",
        dose="1 tablet",
        frequency="three times daily",
        duration="3 days",
        is_confirmed=True,
        status=MedicineStatus.ACTIVE,
    )
    session.add(med4)

    # Confirmed Medicine C: Disprin 325 (Acetylsalicylic Acid — triggers interaction with Paracetamol)
    norm5 = normalize_medicine("Disprin 325", "325mg")
    med5 = Medicine(
        user_id=user2.id,
        prescription_id=rx2.id,
        raw_name="Disprin 325",
        brand_name="Disprin",
        normalized_ingredient=norm5.ingredient or "Acetylsalicylic Acid",
        strength="325mg",
        dose="1 tablet",
        frequency="once daily",
        duration="5 days",
        is_confirmed=True,
        status=MedicineStatus.ACTIVE,
    )
    session.add(med5)
    await session.flush()

    # Create Duplicate Flag between med3 and med4
    flags = await reconcile.flag_duplicates_for(session, medicine=med4)

    # Reminders for User 2
    rem2 = ReminderSchedule(
        user_id=user2.id,
        medicine_id=med3.id,
        time_of_day=datetime.strptime("09:00:00", "%H:%M:%S").time(),
        frequency="twice_daily",
        is_active=True,
    )
    rem3 = ReminderSchedule(
        user_id=user2.id,
        medicine_id=med5.id,
        time_of_day=datetime.strptime("21:00:00", "%H:%M:%S").time(),
        frequency="daily",
        is_active=True,
    )
    session.add_all([rem2, rem3])

    # Trigger interaction check for User 2
    await session.flush()
    await check_interactions(session, user_id=user2.id)

    await session.commit()
    logger.info("Created Demo User 2 (Breastfeeding) with Duplicate Flag and Moderate DDI alerts.")
    logger.info("Demo database seed complete!")


async def run_seed() -> None:
    async with AsyncSessionLocal() as session:
        await seed_demo_data(session)


if __name__ == "__main__":
    asyncio.run(run_seed())
