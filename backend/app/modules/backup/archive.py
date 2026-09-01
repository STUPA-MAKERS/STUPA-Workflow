"""Archive format: age-encrypted tar of a Postgres dump plus the object bucket.

The layout inside the tar is flat and readable by hand, so an operator with the private
key can open an archive with the standard tools::

    age -d -i key.txt antrag-<ts>.tar.age | tar -tvf -
      manifest.json     format version, app version, alembic head, counts
      db.dump           pg_dump --format=custom
      objects/<key>     one member per object in the attachment bucket

`pyrage` writes the same `age-encryption.org/v1` format as the `age` CLI, so the archive
stays openable without this codebase. That matters for disaster recovery: the platform
must never be the only thing that can read its own backups.

Everything here works on file objects, never on one big `bytes`. An archive holds every
attachment the platform ever stored, so a whole-archive buffer would be the first thing
to break on a real dataset. The caller supplies open temporary files and this module
streams through them.

The functions do the encoding and the encryption only. They run no subprocess and touch
no database, so the unit tests cover them directly. `service.py` supplies the dump and
the objects, and `tasks.py` runs the pg_dump/pg_restore subprocesses.
"""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import IO

# pyrage is a native extension and ships no stubs, so the type checker cannot see
# through `from .pyrage import *` in its `__init__`. The names are verified by the
# unit tests instead.
from pyrage import (
    decrypt_io,  # pyright: ignore[reportAttributeAccessIssue]
    encrypt_io,  # pyright: ignore[reportAttributeAccessIssue]
    x25519,  # pyright: ignore[reportAttributeAccessIssue]
)

from app.modules.backup.models import (
    ARCHIVE_DUMP_NAME,
    ARCHIVE_MANIFEST_NAME,
    ARCHIVE_OBJECT_PREFIX,
)

# Bump this when the layout changes in a way an older reader cannot handle. `read_manifest`
# refuses a higher version rather than guessing at the contents.
ARCHIVE_FORMAT_VERSION = 1

_CHUNK = 1024 * 1024


class ArchiveError(RuntimeError):
    """The archive is unreadable, truncated, or not one of ours."""


@dataclass(slots=True)
class ArchiveManifest:
    """The `manifest.json` member: what the archive holds and where it came from."""

    format_version: int = ARCHIVE_FORMAT_VERSION
    app_version: str | None = None
    schema_revision: str | None = None
    created_at: str | None = None
    object_count: int = 0
    bucket: str | None = None
    extra: dict[str, str] = field(default_factory=dict)

    def to_json(self) -> bytes:
        """Serialize deterministically, so an unchanged archive hashes the same."""
        payload = {
            "formatVersion": self.format_version,
            "appVersion": self.app_version,
            "schemaRevision": self.schema_revision,
            "createdAt": self.created_at,
            "objectCount": self.object_count,
            "bucket": self.bucket,
            "extra": self.extra,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()

    @classmethod
    def from_json(cls, raw: bytes) -> ArchiveManifest:
        """Parse a manifest member.

        Raises:
            ArchiveError: The member is not JSON, or it carries a newer format version
                than this code knows how to read.
        """
        try:
            data = json.loads(raw.decode())
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ArchiveError("manifest is not valid JSON") from exc
        if not isinstance(data, dict):
            raise ArchiveError("manifest is not an object")
        version = data.get("formatVersion")
        if not isinstance(version, int):
            raise ArchiveError("manifest carries no format version")
        if version > ARCHIVE_FORMAT_VERSION:
            raise ArchiveError(
                f"archive format {version} is newer than this platform reads "
                f"({ARCHIVE_FORMAT_VERSION})"
            )
        extra = data.get("extra")
        return cls(
            format_version=version,
            app_version=data.get("appVersion"),
            schema_revision=data.get("schemaRevision"),
            created_at=data.get("createdAt"),
            object_count=data.get("objectCount") or 0,
            bucket=data.get("bucket"),
            extra=extra if isinstance(extra, dict) else {},
        )


def recipient_from_str(value: str) -> x25519.Recipient:
    """Parse the configured age public key.

    Raises:
        ArchiveError: The value is not an age x25519 recipient.
    """
    try:
        return x25519.Recipient.from_str(value.strip())
    except Exception as exc:  # pyrage raises its own RecipientError
        raise ArchiveError("backup_age_recipient is not a valid age public key") from exc


def identity_from_str(value: str) -> x25519.Identity:
    """Parse the age private key that a restore needs.

    The caller reads the key file, so the key material has exactly one path into the
    process. An age key file may carry comment lines above the key, which is what the
    `age-keygen` output looks like, so every line gets a try.

    Raises:
        ArchiveError: The value holds no usable age x25519 identity.
    """
    for line in value.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            return x25519.Identity.from_str(stripped)
        except Exception:  # noqa: S112 — a comment line is not a key, try the next
            continue
    raise ArchiveError("the age identity file holds no usable private key")


def write_tar(
    target: IO[bytes],
    dump: IO[bytes],
    objects: Iterable[tuple[str, IO[bytes]]],
    manifest: ArchiveManifest,
) -> int:
    """Stream the dump plus the objects into an uncompressed tar on `target`.

    `pg_dump --format=custom` compresses already, and the attachments are mostly PDFs
    and images, so a second compression pass would cost time and save almost nothing.

    Args:
        target: Open binary file that receives the tar.
        dump: Open reader over the `pg_dump --format=custom` output.
        objects: `(object key, open reader)` pairs from the attachment bucket. Each
            reader is consumed once and left to the caller to close.
        manifest: Metadata. `object_count` is overwritten with the real count.

    Returns:
        The number of objects written.
    """
    count = 0
    # The manifest goes in last, because only then is the object count known. tar has no
    # index, so a reader scans the members anyway and the order does not matter to it.
    with tarfile.open(fileobj=target, mode="w") as tar:
        _add_stream(tar, ARCHIVE_DUMP_NAME, dump, _size_of(dump))
        for key, reader in objects:
            _add_stream(tar, f"{ARCHIVE_OBJECT_PREFIX}{key}", reader, _size_of(reader))
            count += 1
        manifest.object_count = count
        _add_bytes(tar, ARCHIVE_MANIFEST_NAME, manifest.to_json())
    return count


def _size_of(handle: IO[bytes]) -> int:
    """Return the remaining byte count of a seekable reader, without reading it."""
    start = handle.tell()
    size = handle.seek(0, io.SEEK_END) - start
    handle.seek(start)
    return size


def _tar_info(name: str, size: int) -> tarfile.TarInfo:
    """Build a member header with a fixed mode and no owner or time metadata.

    Zeroing the owner and the mtime keeps identical content producing identical bytes,
    which is what makes the archive checksum meaningful across hosts.
    """
    info = tarfile.TarInfo(name=name)
    info.size = size
    info.mode = 0o600
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    info.mtime = 0
    return info


def _add_stream(tar: tarfile.TarFile, name: str, reader: IO[bytes], size: int) -> None:
    """Append one member, copied from `reader` in chunks."""
    tar.addfile(_tar_info(name, size), reader)


def _add_bytes(tar: tarfile.TarFile, name: str, payload: bytes) -> None:
    """Append one small in-memory member, such as the manifest."""
    tar.addfile(_tar_info(name, len(payload)), io.BytesIO(payload))


def encrypt_stream(
    source: IO[bytes], target: IO[bytes], recipient: x25519.Recipient
) -> tuple[str, int]:
    """Encrypt `source` onto `target` and return the sha256 and size of the ciphertext.

    The checksum covers the encrypted bytes, which is what the object store holds and
    what an import re-checks, so it verifies the transport rather than the plaintext.
    """
    source.seek(0)
    encrypt_io(source, target, [recipient])
    target.seek(0)
    digest = hashlib.sha256()
    size = 0
    while chunk := target.read(_CHUNK):
        digest.update(chunk)
        size += len(chunk)
    target.seek(0)
    return digest.hexdigest(), size


def decrypt_stream(source: IO[bytes], target: IO[bytes], identity: x25519.Identity) -> None:
    """Decrypt an archive from `source` onto `target`.

    Raises:
        ArchiveError: The bytes are not an age archive, or this identity does not
            open them.
    """
    source.seek(0)
    try:
        decrypt_io(source, target, [identity])
    except Exception as exc:  # pyrage raises its own DecryptError
        raise ArchiveError("the archive does not decrypt with the configured age identity") from exc
    target.seek(0)


@contextmanager
def open_tar(handle: IO[bytes]) -> Iterator[tarfile.TarFile]:
    """Open a decrypted tar for reading.

    Raises:
        ArchiveError: The bytes are not a readable tar.
    """
    handle.seek(0)
    try:
        # The close happens in the `finally` below, which is what this contextmanager
        # exists for, so the SIM115 "use a context manager" advice does not apply.
        tar = tarfile.open(fileobj=handle, mode="r")  # noqa: SIM115
    except tarfile.TarError as exc:
        raise ArchiveError("archive is not a readable tar") from exc
    try:
        yield tar
    finally:
        tar.close()


def read_manifest(tar: tarfile.TarFile) -> ArchiveManifest:
    """Read `manifest.json` out of an open tar.

    Raises:
        ArchiveError: The tar carries no manifest.
    """
    return ArchiveManifest.from_json(_member_bytes(tar, ARCHIVE_MANIFEST_NAME))


def extract_dump(tar: tarfile.TarFile, target: IO[bytes]) -> int:
    """Copy `db.dump` out of an open tar onto `target` and return its size.

    Raises:
        ArchiveError: The tar carries no dump.
    """
    handle = _member_handle(tar, ARCHIVE_DUMP_NAME)
    size = 0
    while chunk := handle.read(_CHUNK):
        target.write(chunk)
        size += len(chunk)
    target.flush()
    return size


def iter_objects(tar: tarfile.TarFile) -> Iterator[tuple[str, bytes]]:
    """Yield `(object key, bytes)` for every `objects/` member of an open tar.

    A member whose name escapes the `objects/` prefix is skipped rather than written.
    These names go straight to the object store, so a crafted archive must not be able
    to place a file wherever it likes. One attachment at a time stays in memory, which
    the upload cap already bounds.
    """
    for member in tar.getmembers():
        if not member.isfile() or not member.name.startswith(ARCHIVE_OBJECT_PREFIX):
            continue
        key = member.name[len(ARCHIVE_OBJECT_PREFIX) :]
        if not _safe_object_key(key):
            continue
        handle = tar.extractfile(member)
        if handle is None:
            continue
        yield key, handle.read()


def _safe_object_key(key: str) -> bool:
    """Reject an empty, absolute or traversing object key."""
    if not key or key.startswith("/") or "\\" in key:
        return False
    return ".." not in key.split("/")


def _member_handle(tar: tarfile.TarFile, name: str) -> IO[bytes]:
    """Return a reader over one named member.

    Raises:
        ArchiveError: The member is missing or is not a regular file.
    """
    try:
        handle = tar.extractfile(name)
    except KeyError as exc:
        raise ArchiveError(f"archive carries no {name}") from exc
    if handle is None:
        raise ArchiveError(f"archive carries no {name}")
    return handle


def _member_bytes(tar: tarfile.TarFile, name: str) -> bytes:
    """Read one small named member in full."""
    return _member_handle(tar, name).read()


def sha256_of(handle: IO[bytes]) -> str:
    """Return the hex sha256 of a seekable reader, leaving it rewound."""
    handle.seek(0)
    digest = hashlib.sha256()
    while chunk := handle.read(_CHUNK):
        digest.update(chunk)
    handle.seek(0)
    return digest.hexdigest()
