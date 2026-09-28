"""Uploaded prescription documents."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, utcnow
from app.models.enums import MedicineSourceType, PrescriptionFileType, enum_column

if TYPE_CHECKING:
    from app.models.medicine import Medicine
    from app.models.user import User


class Prescription(SoftDeleteMixin, Base):
    __tablename__ = "prescriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    # The storage-relative path ("prescriptions/1/<uuid>.pdf"), kept alongside
    # file_url on purpose. file_url is whatever the client should fetch; this is
    # the opaque key the StorageService needs in order to delete. Deriving one
    # from the other would tie every backend to the local /files URL scheme and
    # make the S3 swap a rewrite instead of a small change.
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    file_type: Mapped[PrescriptionFileType] = mapped_column(
        enum_column(PrescriptionFileType, "prescription_file_type"),
        nullable=False,
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        server_default=func.now(),
    )
    source_type: Mapped[MedicineSourceType] = mapped_column(
        enum_column(MedicineSourceType, "medicine_source_type"),
        nullable=False,
    )

    user: Mapped["User"] = relationship(back_populates="prescriptions")
    # passive_deletes: medicines.prescription_id is ON DELETE CASCADE, so let
    # the database remove them rather than nulling a NOT NULL foreign key.
    medicines: Mapped[list["Medicine"]] = relationship(
        back_populates="prescription",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
