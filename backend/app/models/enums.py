"""Domain enumerations, shared by models today and by schemas/services later.

Each enum maps to a native PostgreSQL ``ENUM`` type. The type name is fixed
explicitly so a later ``ALTER TYPE`` migration has a stable identifier to
target -- never rename one of these strings once a database exists.
"""

from enum import StrEnum

from sqlalchemy import Enum as SAEnum


class UserContextType(StrEnum):
    """The maternal context a safety check should be evaluated against."""

    GENERAL = "general"
    PLANNING_PREGNANCY = "planning_pregnancy"
    PREGNANT = "pregnant"
    BREASTFEEDING = "breastfeeding"


class PrescriptionFileType(StrEnum):
    IMAGE = "image"
    PDF = "pdf"


class MedicineSourceType(StrEnum):
    PRESCRIPTION = "prescription"
    OTC = "otc"
    SELF_REPORTED = "self_reported"


class MedicineStatus(StrEnum):
    """Lifecycle of a medicine row on the user's list.

    ``REJECTED`` is distinct from ``DISCONTINUED`` on purpose. Discontinuing
    means "I was taking this and stopped"; rejecting means "this OCR line is
    not a real medicine I take", which is a different fact about a different
    kind of row. Collapsing them would make the confirmed list lie.
    """

    ACTIVE = "active"
    DISCONTINUED = "discontinued"
    REJECTED = "rejected"


class InteractionSeverity(StrEnum):
    HIGH = "high"
    MODERATE = "moderate"
    LOW = "low"
    NONE = "none"


def enum_column(enum_cls: type[StrEnum], type_name: str) -> SAEnum:
    """Build a native-Postgres enum column that stores the enum *values*.

    Without ``values_callable`` SQLAlchemy persists the Python member *name*, so
    ``PLANNING_PREGNANCY`` would land in the database instead of the intended
    ``planning_pregnancy``. Funnelling every enum column through this helper
    keeps that behaviour in one place.
    """
    return SAEnum(
        enum_cls,
        name=type_name,
        values_callable=lambda cls: [member.value for member in cls],
        validate_strings=True,
    )
