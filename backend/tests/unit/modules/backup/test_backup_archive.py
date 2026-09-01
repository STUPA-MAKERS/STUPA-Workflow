"""Unit tests for the archive layer: tar layout, age round trip, manifest and safety.

The module is pure, so the tests drive it directly with real temporary files and a
real age key pair. `pyrage` is fast enough that a generated key per test costs nothing,
and using the real thing is what proves the archive stays readable by the `age` CLI.
"""

from __future__ import annotations

import io
import json
import tarfile

import pytest
from pyrage import x25519  # pyright: ignore[reportAttributeAccessIssue]

from app.modules.backup import archive as arch
from app.modules.backup.models import (
    ARCHIVE_DUMP_NAME,
    ARCHIVE_MANIFEST_NAME,
    ARCHIVE_OBJECT_PREFIX,
)


def _identity() -> x25519.Identity:
    return x25519.Identity.generate()


def _tar_with(objects: dict[str, bytes], dump: bytes = b"DUMP") -> io.BytesIO:
    """Build an in-memory archive tar holding `dump` plus `objects`."""
    target = io.BytesIO()
    readers = [(key, io.BytesIO(value)) for key, value in objects.items()]
    arch.write_tar(target, io.BytesIO(dump), readers, arch.ArchiveManifest())
    target.seek(0)
    return target


# ------------------------------------------------------------------------ manifest


def test_manifest_round_trips_through_json() -> None:
    manifest = arch.ArchiveManifest(
        app_version="1.2.3",
        schema_revision="f3b3f1a022b5",
        created_at="2026-09-01T00:00:00+00:00",
        object_count=7,
        bucket="attachments",
        extra={"note": "nightly"},
    )
    parsed = arch.ArchiveManifest.from_json(manifest.to_json())
    assert parsed == manifest


def test_manifest_serializes_deterministically() -> None:
    """The same content must hash the same, or the checksum means nothing."""
    first = arch.ArchiveManifest(app_version="1.0", bucket="b").to_json()
    second = arch.ArchiveManifest(bucket="b", app_version="1.0").to_json()
    assert first == second


def test_manifest_rejects_a_newer_format_version() -> None:
    """A newer archive must fail loudly rather than be read with the wrong rules."""
    raw = json.dumps({"formatVersion": arch.ARCHIVE_FORMAT_VERSION + 1}).encode()
    with pytest.raises(arch.ArchiveError, match="newer than this platform reads"):
        arch.ArchiveManifest.from_json(raw)


@pytest.mark.parametrize(
    ("raw", "match"),
    [
        (b"not json at all", "not valid JSON"),
        (b"[1, 2, 3]", "not an object"),
        (b'{"appVersion": "1.0"}', "no format version"),
    ],
)
def test_manifest_rejects_malformed_input(raw: bytes, match: str) -> None:
    with pytest.raises(arch.ArchiveError, match=match):
        arch.ArchiveManifest.from_json(raw)


def test_manifest_tolerates_a_non_dict_extra() -> None:
    raw = json.dumps({"formatVersion": 1, "extra": "nonsense"}).encode()
    assert arch.ArchiveManifest.from_json(raw).extra == {}


# ----------------------------------------------------------------------------- keys


def test_recipient_and_identity_parse_from_their_string_forms() -> None:
    identity = _identity()
    recipient = arch.recipient_from_str(str(identity.to_public()))
    parsed = arch.identity_from_str(str(identity))
    payload = io.BytesIO(b"secret")
    encrypted = io.BytesIO()
    arch.encrypt_stream(payload, encrypted, recipient)
    plain = io.BytesIO()
    arch.decrypt_stream(encrypted, plain, parsed)
    assert plain.getvalue() == b"secret"


def test_identity_skips_comment_lines_like_age_keygen_writes() -> None:
    """`age-keygen` puts comments above the key, so the parser must look past them."""
    identity = _identity()
    text = f"# created: 2026-09-01\n# public key: {identity.to_public()}\n{identity}\n"
    assert str(arch.identity_from_str(text)) == str(identity)


def test_recipient_rejects_a_value_that_is_not_a_key() -> None:
    with pytest.raises(arch.ArchiveError, match="not a valid age public key"):
        arch.recipient_from_str("definitely-not-an-age-key")


def test_identity_rejects_a_file_with_no_key() -> None:
    with pytest.raises(arch.ArchiveError, match="no usable private key"):
        arch.identity_from_str("# only a comment\n\n")


# ------------------------------------------------------------------------------ tar


def test_tar_holds_the_dump_the_objects_and_the_manifest() -> None:
    tar_bytes = _tar_with({"a.pdf": b"one", "nested/b.png": b"two"})
    with tarfile.open(fileobj=tar_bytes, mode="r") as tar:
        names = set(tar.getnames())
    assert names == {
        ARCHIVE_DUMP_NAME,
        ARCHIVE_MANIFEST_NAME,
        f"{ARCHIVE_OBJECT_PREFIX}a.pdf",
        f"{ARCHIVE_OBJECT_PREFIX}nested/b.png",
    }


def test_write_tar_counts_the_objects_and_stamps_the_manifest() -> None:
    manifest = arch.ArchiveManifest()
    target = io.BytesIO()
    readers = [("a", io.BytesIO(b"1")), ("b", io.BytesIO(b"2"))]
    count = arch.write_tar(target, io.BytesIO(b"DUMP"), readers, manifest)
    assert count == 2
    assert manifest.object_count == 2


def test_tar_members_carry_no_owner_or_time_metadata() -> None:
    """Identical content must produce identical bytes across hosts and runs."""
    first = _tar_with({"a": b"x"}).getvalue()
    second = _tar_with({"a": b"x"}).getvalue()
    assert first == second


def test_extract_dump_returns_the_dump_bytes() -> None:
    tar_bytes = _tar_with({"a": b"x"}, dump=b"PGDUMP-PAYLOAD")
    out = io.BytesIO()
    with arch.open_tar(tar_bytes) as tar:
        size = arch.extract_dump(tar, out)
    assert out.getvalue() == b"PGDUMP-PAYLOAD"
    assert size == len(b"PGDUMP-PAYLOAD")


def test_iter_objects_yields_every_stored_object() -> None:
    tar_bytes = _tar_with({"a.pdf": b"one", "deep/b.png": b"two"})
    with arch.open_tar(tar_bytes) as tar:
        assert dict(arch.iter_objects(tar)) == {"a.pdf": b"one", "deep/b.png": b"two"}


def test_read_manifest_finds_the_member() -> None:
    tar_bytes = _tar_with({})
    with arch.open_tar(tar_bytes) as tar:
        assert arch.read_manifest(tar).format_version == arch.ARCHIVE_FORMAT_VERSION


@pytest.mark.parametrize("hostile", ["../escape", "/absolute", "a/../../escape", ""])
def test_iter_objects_skips_a_key_that_escapes_the_prefix(hostile: str) -> None:
    """A crafted archive must not steer a restore into writing outside the bucket."""
    target = io.BytesIO()
    with tarfile.open(fileobj=target, mode="w") as tar:
        info = tarfile.TarInfo(name=f"{ARCHIVE_OBJECT_PREFIX}{hostile}")
        info.size = 3
        tar.addfile(info, io.BytesIO(b"bad"))
        good = tarfile.TarInfo(name=f"{ARCHIVE_OBJECT_PREFIX}fine.pdf")
        good.size = 4
        tar.addfile(good, io.BytesIO(b"good"))
    with arch.open_tar(target) as tar:
        assert dict(arch.iter_objects(tar)) == {"fine.pdf": b"good"}


def test_iter_objects_ignores_a_member_outside_the_objects_prefix() -> None:
    tar_bytes = _tar_with({"a": b"x"})
    with arch.open_tar(tar_bytes) as tar:
        keys = dict(arch.iter_objects(tar))
    assert ARCHIVE_DUMP_NAME not in keys
    assert ARCHIVE_MANIFEST_NAME not in keys


def test_open_tar_rejects_bytes_that_are_not_a_tar() -> None:
    with (
        pytest.raises(arch.ArchiveError, match="not a readable tar"),
        arch.open_tar(io.BytesIO(b"nowhere near a tar")),
    ):
        pass  # pragma: no cover — open_tar raises before the body runs


@pytest.mark.parametrize("name", [ARCHIVE_DUMP_NAME, ARCHIVE_MANIFEST_NAME])
def test_reading_a_missing_member_fails_clearly(name: str) -> None:
    empty = io.BytesIO()
    with tarfile.open(fileobj=empty, mode="w"):
        pass
    with arch.open_tar(empty) as tar, pytest.raises(arch.ArchiveError, match=name):
        if name == ARCHIVE_DUMP_NAME:
            arch.extract_dump(tar, io.BytesIO())
        else:
            arch.read_manifest(tar)


# ----------------------------------------------------------------------- encryption


def test_archive_round_trips_through_age() -> None:
    identity = _identity()
    tar_bytes = _tar_with({"a.pdf": b"one"}, dump=b"DUMP")
    encrypted = io.BytesIO()
    checksum, size = arch.encrypt_stream(tar_bytes, encrypted, identity.to_public())
    assert len(checksum) == 64
    assert size == len(encrypted.getvalue())

    plain = io.BytesIO()
    arch.decrypt_stream(encrypted, plain, identity)
    with arch.open_tar(plain) as tar:
        assert dict(arch.iter_objects(tar)) == {"a.pdf": b"one"}


def test_encrypted_archive_carries_the_standard_age_header() -> None:
    """The `age` CLI must be able to open an archive without this codebase."""
    encrypted = io.BytesIO()
    arch.encrypt_stream(io.BytesIO(b"x"), encrypted, _identity().to_public())
    assert encrypted.getvalue().startswith(b"age-encryption.org/v1\n")


def test_decrypt_rejects_a_foreign_key() -> None:
    encrypted = io.BytesIO()
    arch.encrypt_stream(io.BytesIO(b"x"), encrypted, _identity().to_public())
    with pytest.raises(arch.ArchiveError, match="does not decrypt"):
        arch.decrypt_stream(encrypted, io.BytesIO(), _identity())


def test_checksum_matches_the_stored_ciphertext() -> None:
    encrypted = io.BytesIO()
    checksum, _ = arch.encrypt_stream(io.BytesIO(b"x"), encrypted, _identity().to_public())
    assert arch.sha256_of(encrypted) == checksum


def test_sha256_leaves_the_reader_rewound() -> None:
    handle = io.BytesIO(b"payload")
    arch.sha256_of(handle)
    assert handle.read() == b"payload"
