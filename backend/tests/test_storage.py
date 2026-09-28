"""Unit tests for the storage backend and content sniffing. No database required."""

from pathlib import Path

import pytest

from app.models.enums import PrescriptionFileType
from app.services.storage import LocalStorageService, StorageError, sniff_image_type

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
PDF = b"%PDF-1.7\n" + b"\x00" * 32


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorageService:
    return LocalStorageService(tmp_path / "storage", url_prefix="/files")


# --- content sniffing -------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "expected_type", "expected_ext"),
    [
        (JPEG, PrescriptionFileType.IMAGE, "jpg"),
        (PNG, PrescriptionFileType.IMAGE, "png"),
        (b"GIF89a" + b"\x00" * 8, PrescriptionFileType.IMAGE, "gif"),
        (b"BM" + b"\x00" * 8, PrescriptionFileType.IMAGE, "bmp"),
        (PDF, PrescriptionFileType.PDF, "pdf"),
    ],
)
def test_recognises_valid_content(
    data: bytes, expected_type: PrescriptionFileType, expected_ext: str
) -> None:
    assert sniff_image_type(data) == (expected_type, expected_ext)


def test_recognises_webp_only_when_the_container_says_webp() -> None:
    """'RIFF' alone also matches WAV and AVI.

    Accepting a bare RIFF header would let a .wav be stored and then served as
    an image, which is how a content-type confusion bug starts.
    """
    webp = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 16
    wav = b"RIFF" + b"\x00\x00\x00\x00" + b"WAVE" + b"\x00" * 16
    assert sniff_image_type(webp) == (PrescriptionFileType.IMAGE, "webp")
    assert sniff_image_type(wav) is None


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"not a real file",
        b"<html><body>hi</body></html>",
        # A script renamed to .jpg. Must not be stored.
        b"#!/bin/sh\nrm -rf /\n",
        # PDF signature must be at the start, not merely present.
        b"\x00\x00%PDF-1.4",
    ],
)
def test_rejects_unrecognised_content(data: bytes) -> None:
    assert sniff_image_type(data) is None


# --- save / read / delete ---------------------------------------------------


async def test_save_writes_under_the_expected_key_and_returns_a_url(
    storage: LocalStorageService,
) -> None:
    stored = await storage.save(user_id=7, data=PNG, extension="png")

    assert stored.key.startswith("prescriptions/7/")
    assert stored.key.endswith(".png")
    assert stored.url == f"/files/{stored.key}"
    assert stored.size == len(PNG)
    assert stored.file_type is PrescriptionFileType.IMAGE

    on_disk = storage.root / stored.key
    assert on_disk.is_file()
    assert on_disk.read_bytes() == PNG


async def test_generated_names_are_unique(storage: LocalStorageService) -> None:
    """Two identical uploads get different keys, so neither can clobber the other."""
    first = await storage.save(user_id=1, data=PNG, extension="png")
    second = await storage.save(user_id=1, data=PNG, extension="png")
    assert first.key != second.key


async def test_delete_removes_the_file_and_prunes_the_directory(
    storage: LocalStorageService,
) -> None:
    stored = await storage.save(user_id=3, data=PNG, extension="png")
    user_dir = storage.root / "prescriptions" / "3"
    assert user_dir.is_dir()

    await storage.delete(stored.key)

    assert not (storage.root / stored.key).exists()
    # The per-user directory goes too, rather than accumulating empty folders.
    assert not user_dir.exists()
    # ...but the storage root itself survives.
    assert storage.root.is_dir()


async def test_deleting_a_missing_file_is_not_an_error(
    storage: LocalStorageService,
) -> None:
    """Delete is called after the row is already tombstoned.

    A retried request must not turn into a 500 just because the bytes are
    already gone.
    """
    await storage.delete("prescriptions/3/does-not-exist.png")


async def test_delete_keeps_sibling_uploads_in_the_same_user_directory(
    storage: LocalStorageService,
) -> None:
    """The rmdir pruning must not take a concurrently-written sibling with it."""
    keeper = await storage.save(user_id=5, data=PNG, extension="png")
    doomed = await storage.save(user_id=5, data=JPEG, extension="jpg")

    await storage.delete(doomed.key)

    assert (storage.root / keeper.key).is_file()
    assert not (storage.root / doomed.key).exists()


@pytest.mark.parametrize(
    "hostile_key",
    [
        "../../app/main.py",
        "prescriptions/../../escape.png",
        "/etc/passwd",
    ],
)
async def test_refuses_keys_that_escape_the_storage_root(
    storage: LocalStorageService, hostile_key: str
) -> None:
    """Traversal is refused even though keys are generated internally.

    Defense in depth: the day someone adds a key derived from user input, this is
    what stops it.
    """
    with pytest.raises(StorageError):
        await storage.read(hostile_key)
    with pytest.raises(StorageError):
        await storage.delete(hostile_key)


async def test_extension_is_normalised(storage: LocalStorageService) -> None:
    stored = await storage.save(user_id=1, data=PDF, extension=".PDF")
    assert stored.key.endswith(".pdf")
    assert stored.file_type is PrescriptionFileType.PDF
