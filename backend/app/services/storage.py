"""Pluggable file storage for uploaded prescriptions.

The rest of the app talks to the :class:`StorageService` protocol and never to
the filesystem directly, so moving to S3/MinIO/GCS is a settings change plus one
new class. The contract is deliberately narrow -- put, delete, exists, read --
because every extra method is another thing a cloud backend has to reimplement.
"""

from __future__ import annotations

import logging
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from anyio import to_thread

from app.core.config import get_settings
from app.models.enums import PrescriptionFileType

logger = logging.getLogger(__name__)

__all__ = [
    "StorageError",
    "StorageService",
    "LocalStorageService",
    "StoredFile",
    "get_storage_service",
    "local_storage_root",
    "reset_storage_service",
    "sniff_image_type",
]


class StorageError(RuntimeError):
    """Raised when the backing store cannot satisfy a request."""


@dataclass(frozen=True, slots=True)
class StoredFile:
    """Where a file ended up, and how to get at it again.

    ``key`` is the storage-relative path and is what :meth:`StorageService.delete`
    needs. ``url`` is what a client should fetch, and may point somewhere else
    entirely once the backend is a bucket.
    """

    key: str
    url: str
    size: int
    file_type: PrescriptionFileType
    extension: str


@runtime_checkable
class StorageService(Protocol):
    """Minimal blob-store contract."""

    async def save(
        self, *, user_id: int, data: bytes, extension: str
    ) -> StoredFile: ...

    async def delete(self, key: str) -> None: ...

    async def exists(self, key: str) -> bool: ...

    def public_url(self, key: str) -> str: ...


# --- content sniffing -------------------------------------------------------

# Magic-byte signatures. The client-supplied Content-Type is attacker-controlled
# and so is the filename, so neither can be trusted to decide what we store or
# later serve back. Verified bytes are the only reason we can safely put these
# files under a public mount.
_IMAGE_SIGNATURES: tuple[tuple[bytes, PrescriptionFileType, str], ...] = (
    (b"\xff\xd8\xff", PrescriptionFileType.IMAGE, "jpg"),
    (b"\x89PNG\r\n\x1a\n", PrescriptionFileType.IMAGE, "png"),
    (b"GIF87a", PrescriptionFileType.IMAGE, "gif"),
    (b"GIF89a", PrescriptionFileType.IMAGE, "gif"),
    (b"BM", PrescriptionFileType.IMAGE, "bmp"),
    (b"II*\x00", PrescriptionFileType.IMAGE, "tif"),
    (b"MM\x00*", PrescriptionFileType.IMAGE, "tif"),
    (b"RIFF", PrescriptionFileType.IMAGE, "webp"),  # verified further below
)

PDF_SIGNATURE = b"%PDF-"


def sniff_image_type(data: bytes) -> tuple[PrescriptionFileType, str] | None:
    """Return ``(file_type, extension)`` for recognised content, else ``None``.

    PDF first: ``%PDF-`` is checked at offset 0, whereas some containers carry
    leading padding before the real payload.
    """
    if not data:
        return None
    if data.startswith(PDF_SIGNATURE):
        return PrescriptionFileType.PDF, "pdf"
    for signature, file_type, extension in _IMAGE_SIGNATURES:
        if not data.startswith(signature):
            continue
        # WebP is a RIFF container, so "RIFF" alone also matches WAV/AVI. The
        # form type lives at offset 8 and must say WEBP.
        if extension == "webp":
            if data[8:12] != b"WEBP":
                continue
        return file_type, extension
    return None


# --- local filesystem -------------------------------------------------------


class LocalStorageService:
    """Stores blobs under a root directory and serves them from ``/files``.

    Write path::

        <storage_root>/prescriptions/<user_id>/<uuid4>.<ext>

    The filename is always generated here, never taken from the client: an
    attacker-supplied name like ``../../app/main.py`` would otherwise escape the
    upload directory entirely.
    """

    def __init__(self, root: Path, *, url_prefix: str) -> None:
        self._root = Path(root).resolve()
        self._url_prefix = url_prefix.rstrip("/")
        # check_dir=False: a brand-new checkout has no storage/ yet, and
        # raising at construction would make `import app.main` fail.
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    async def save(self, *, user_id: int, data: bytes, extension: str) -> StoredFile:
        # uuid4 rather than a timestamp+counter: the name is part of a public
        # URL, so it must be unguessable, and it doubles as the de-duplication
        # key if a client retries an upload.
        name = f"{uuid.uuid4().hex}.{extension.lstrip('.').lower()}"
        key = f"prescriptions/{user_id}/{name}"
        target = self._resolve(key)
        # Filesystem calls run in a worker thread. A 10 MB write is milliseconds
        # of blocking, but it is blocking *on the event loop* -- which means it
        # stalls every other in-flight request, not just this one. The upload
        # limit keeps the worst case bounded, and offloading keeps the loop free.
        await to_thread.run_sync(self._write_exclusive, target, data)
        logger.info("Stored upload key=%s bytes=%d", key, len(data))
        return StoredFile(
            key=key,
            url=self.public_url(key),
            size=len(data),
            file_type=PrescriptionFileType.PDF
            if extension.lstrip(".").lower() == "pdf"
            else PrescriptionFileType.IMAGE,
            extension=extension.lstrip(".").lower(),
        )

    @staticmethod
    def _write_exclusive(target: Path, data: bytes) -> None:
        """Create the file, refusing to overwrite. Runs in a worker thread.

        ``mkdir`` and the exclusive ``open`` happen together so two uploads for
        the same user cannot race between the directory check and the write.
        Mode ``xb`` is what makes a name collision fail loudly rather than
        silently clobbering another user's file.
        """
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "xb") as handle:
                handle.write(data)
        except FileExistsError as exc:  # pragma: no cover - uuid4 collision
            raise StorageError(f"storage key collision: {target.name}") from exc
        except OSError as exc:
            raise StorageError(f"could not write {target}: {exc}") from exc

    async def delete(self, key: str) -> None:
        """Remove a stored file. Missing files are not an error.

        Delete is called after the row is already tombstoned, so a 404 here
        usually means a retried request, not a bug.
        """
        target = self._resolve(key)
        await to_thread.run_sync(self._unlink_and_prune, target)
        logger.info("Deleted upload key=%s", key)

    def _unlink_and_prune(self, target: Path) -> None:
        """Remove a file and any directories left empty. Runs in a worker thread.

        Walks up towards -- but never past -- the storage root, stopping at the
        first directory that is still non-empty. Pruning is best-effort: another
        upload for the same user may be racing us, in which case ``rmdir`` fails
        and the directory is left for the next request to reuse.
        """
        try:
            target.unlink(missing_ok=True)
        except OSError as exc:  # pragma: no cover - permissions/lock
            raise StorageError(f"could not delete {target}: {exc}") from exc

        parent = target.parent
        while parent != self._root and parent.is_dir():
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent

    async def exists(self, key: str) -> bool:
        return await to_thread.run_sync(self._resolve(key).is_file)

    async def read(self, key: str) -> bytes:
        target = self._resolve(key)
        try:
            return await to_thread.run_sync(target.read_bytes)
        except OSError as exc:
            raise StorageError(f"could not read {key}: {exc}") from exc

    def public_url(self, key: str) -> str:
        return f"{self._url_prefix}/{key}"

    def _resolve(self, key: str) -> Path:
        """Map a storage key to an absolute path, refusing to escape the root.

        Belt and braces: keys are generated internally, but this method is the
        last line of defence against a traversal if that ever stops being true.
        """
        candidate = (self._root / key).resolve()
        if not candidate.is_relative_to(self._root):
            raise StorageError(f"refusing to access {key!r} outside the storage root")
        return candidate

    def clear(self) -> None:  # pragma: no cover - test helper
        shutil.rmtree(self._root, ignore_errors=True)
        self._root.mkdir(parents=True, exist_ok=True)


_service: StorageService | None = None


def get_storage_service() -> StorageService:
    """Return the process-wide storage backend.

    Cached so every request shares one root. Swapping implementations means
    assigning here (or selecting on a Settings.backend field) -- no call site
    changes.
    """
    global _service
    if _service is None:
        settings = get_settings()
        _service = LocalStorageService(
            Path(settings.storage_root), url_prefix=settings.storage_url_prefix
        )
    return _service


def reset_storage_service() -> None:
    """Drop the cached backend. Used by tests that repoint ``storage_root``."""
    global _service
    _service = None


def local_storage_root() -> Path | None:
    """Return the on-disk root when the local backend is active, else ``None``.

    Exists so the static mount in ``main.py`` can be conditional instead of
    reaching into a backend-specific attribute. A cloud backend has no local
    directory, and mounting ``Settings.storage_root`` for it would serve an empty
    folder at ``/files`` while every real URL pointed somewhere else.
    """
    service = get_storage_service()
    return service.root if isinstance(service, LocalStorageService) else None
