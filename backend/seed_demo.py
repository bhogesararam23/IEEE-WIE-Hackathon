"""Single-command database reset, migration, and demo seed script.

Run this command before a demo or presentation:
    python seed_demo.py

Or inside docker compose:
    docker compose exec app python seed_demo.py
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

try:
    from alembic import command
    from alembic.config import Config
    HAS_ALEMBIC = True
except ImportError:
    HAS_ALEMBIC = False

from sqlalchemy import text

from app.core.database import AsyncSessionLocal, engine
from app.seed import seed_demo_data

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("seed_demo")


async def reset_database() -> None:
    """Cleanly truncate all domain tables so seed runs from a pristine state."""
    logger.info("Resetting domain tables...")
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE TABLE evidence_references, interaction_alert_medicines, "
                "interaction_alerts, reminder_schedules, duplicate_flags, medicines, "
                "prescriptions, user_profiles, audit_logs, users RESTART IDENTITY CASCADE;"
            )
        )
    logger.info("Database tables truncated successfully.")


def run_migrations() -> None:
    """Apply Alembic migrations to ensure schema is at head."""
    if not HAS_ALEMBIC:
        logger.warning("Alembic package not available in local environment; skipping migration check.")
        return
    logger.info("Running Alembic migrations (upgrade head)...")
    alembic_ini_path = backend_dir / "alembic.ini"
    alembic_cfg = Config(str(alembic_ini_path))
    command.upgrade(alembic_cfg, "head")
    logger.info("Alembic migrations up to date.")


async def main() -> None:
    print("=" * 60)
    print("HerMediSafe — Pre-Presentation Database Reset & Seed")
    print("=" * 60)

    await reset_database()

    async with AsyncSessionLocal() as session:
        await seed_demo_data(session)

    print("\n[SUCCESS] Seed process complete!")
    print("Demo Users Created:")
    print("  1. demo_pregnant@hermedisafe.org       / DemoUser123!")
    print("     (Context: Pregnant T2 | HIGH severity DDI: Ciprofloxacin + Moxifloxacin)")
    print("  2. demo_breastfeeding@hermedisafe.org    / DemoUser123!")
    print("     (Context: Breastfeeding | Duplicate: Crocin + Dolo | Alert: Paracetamol + Aspirin)")
    print("=" * 60)


if __name__ == "__main__":
    run_migrations()
    asyncio.run(main())
