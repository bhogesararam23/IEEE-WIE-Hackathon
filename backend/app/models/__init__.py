"""SQLAlchemy models. Import every model here so Alembic can discover them.

Alembic autogenerates against ``Base.metadata``, which only knows about a model
once its module has been imported. A new model that is not re-exported below
will be silently skipped by ``--autogenerate``.
"""

from app.models.audit import AuditLog
from app.models.base import Base, SoftDeleteMixin, TimestampMixin
from app.models.enums import (
    InteractionSeverity,
    MedicineSourceType,
    MedicineStatus,
    PrescriptionFileType,
    UserContextType,
)
from app.models.interaction import (
    EvidenceReference,
    InteractionAlert,
    interaction_alert_medicines,
)
from app.models.medicine import DuplicateFlag, Medicine
from app.models.prescription import Prescription
from app.models.reminder import ReminderSchedule
from app.models.user import User, UserProfile

__all__ = [
    "Base",
    "SoftDeleteMixin",
    "TimestampMixin",
    # Enums
    "InteractionSeverity",
    "MedicineSourceType",
    "MedicineStatus",
    "PrescriptionFileType",
    "UserContextType",
    # Models
    "AuditLog",
    "DuplicateFlag",
    "EvidenceReference",
    "InteractionAlert",
    "Medicine",
    "Prescription",
    "ReminderSchedule",
    "User",
    "UserProfile",
    # Join tables
    "interaction_alert_medicines",
]
