"""MIME sniffing (libmagic) + type allowlist.

Content decides, not the extension: ``sniff_mime`` reads the magic header of the bytes.
``validate_upload`` rejects when the sniffed type is not in the allowlist or does not
match the file extension (sniff != extension → 415), so ``evil.exe`` cannot masquerade
as ``foto.png``.

``python-magic`` (libmagic) is imported lazily — the system lib is only needed where
uploads actually happen (worker/API runtime), not in contract CI.
"""

from __future__ import annotations

import io
import os
import zipfile

# Allowed sniffed MIME types (PDF / image / Office).
ALLOWED_MIME_TYPES: frozenset[str] = frozenset(
    {
        "application/pdf",
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        # Office (legacy + OOXML). libmagic sometimes sniffs OOXML as application/zip
        # → zip is allowed only for .docx/.xlsx/.pptx, and then only when the container
        # carries the OOXML structure (see _is_ooxml_container).
        "application/zip",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.oasis.opendocument.text",
        "application/vnd.oasis.opendocument.spreadsheet",
        "application/vnd.oasis.opendocument.presentation",
    }
)

# Extension → acceptable sniffed MIME types. OOXML containers often sniff as
# ``application/zip`` (older libmagic) → deliberately allowed too.
_OOXML_ZIP = {"application/zip"}
_EXT_TO_MIME: dict[str, frozenset[str]] = {
    ".pdf": frozenset({"application/pdf"}),
    ".png": frozenset({"image/png"}),
    ".jpg": frozenset({"image/jpeg"}),
    ".jpeg": frozenset({"image/jpeg"}),
    ".gif": frozenset({"image/gif"}),
    ".webp": frozenset({"image/webp"}),
    ".doc": frozenset({"application/msword"}),
    ".docx": frozenset(
        {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
        | _OOXML_ZIP
    ),
    ".xls": frozenset({"application/vnd.ms-excel"}),
    ".xlsx": frozenset(
        {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"} | _OOXML_ZIP
    ),
    ".ppt": frozenset({"application/vnd.ms-powerpoint"}),
    ".pptx": frozenset(
        {"application/vnd.openxmlformats-officedocument.presentationml.presentation"}
        | _OOXML_ZIP
    ),
    ".odt": frozenset({"application/vnd.oasis.opendocument.text"}),
    ".ods": frozenset({"application/vnd.oasis.opendocument.spreadsheet"}),
    ".odp": frozenset({"application/vnd.oasis.opendocument.presentation"}),
}

# OOXML extension → expected top-level dir in the ZIP container. Used for the
# structural check when libmagic sniffs OOXML only as ``application/zip``: a real
# OOXML package contains ``[Content_Types].xml`` and the format-specific dir
# (word/ | xl/ | ppt/), so an arbitrary ZIP cannot pose as an Office document.
_OOXML_REQUIRED_DIR: dict[str, str] = {
    ".docx": "word/",
    ".xlsx": "xl/",
    ".pptx": "ppt/",
}


class MimeRejected(Exception):
    """File not accepted (disallowed type or sniff != extension)."""


def sniff_mime(data: bytes) -> str:
    """Sniffed MIME type of the bytes (libmagic). Empty input → ``application/x-empty``."""
    if not data:
        return "application/x-empty"
    import magic  # lazy: libmagic only needed on the upload path

    return magic.from_buffer(data, mime=True)


def file_extension(filename: str | None) -> str:
    """Lowercased extension including the dot (``""`` if none)."""
    if not filename:
        return ""
    return os.path.splitext(filename)[1].lower()


# Allowed characters in the stored filename (everything else → ``_``).
_FILENAME_SAFE = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._- "
)
_FILENAME_MAX = 200


def sanitize_filename(filename: str | None) -> str:
    """Harden a filename: drop path components, replace control/special characters.

    Protects both the ``storage_key`` (no ``../`` traversal, no NUL/slashes) and the
    stored display name. Falls back to ``upload`` if nothing usable remains after
    cleaning; caps the length."""
    raw = (filename or "").replace("\\", "/")
    base = os.path.basename(raw).strip()  # drop path components (incl. ``../``)
    cleaned = "".join(c if c in _FILENAME_SAFE else "_" for c in base).strip(" .")
    cleaned = cleaned[:_FILENAME_MAX]
    return cleaned or "upload"


def _is_ooxml_container(data: bytes, ext: str) -> bool:
    """Whether ``data`` is a real OOXML package for ``ext``.

    Requires a readable ZIP container with ``[Content_Types].xml`` and the
    format-specific top-level dir (``word/``/``xl/``/``ppt/``), so an arbitrary ZIP
    posing as ``.docx/.xlsx/.pptx`` is rejected even though libmagic may only sniff
    it as ``application/zip``.
    """
    required_dir = _OOXML_REQUIRED_DIR.get(ext)
    if required_dir is None:
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
    except (zipfile.BadZipFile, OSError):
        return False
    if "[Content_Types].xml" not in names:
        return False
    return any(name.startswith(required_dir) for name in names)


def validate_upload(filename: str | None, data: bytes) -> str:
    """Validate bytes → sniffed MIME type, or raise :class:`MimeRejected`.

    Rules:

    1. Sniffed type must be in :data:`ALLOWED_MIME_TYPES`.
    2. Extension must be known and the sniffed type must match it (sniff != extension
       → reject). Content counts, not the claimed extension.
    3. If an OOXML upload sniffs only as ``application/zip`` (older libmagic), the ZIP
       container must additionally carry the OOXML structure (``[Content_Types].xml`` +
       ``word/``/``xl/``/``ppt/``) — otherwise it counts as an arbitrary ZIP and is
       rejected.
    """
    sniffed = sniff_mime(data)
    if sniffed not in ALLOWED_MIME_TYPES:
        raise MimeRejected(f"File type not allowed: {sniffed}")
    ext = file_extension(filename)
    allowed_for_ext = _EXT_TO_MIME.get(ext)
    if allowed_for_ext is None:
        raise MimeRejected(f"Unsupported file extension: {ext or '(none)'}")
    if sniffed not in allowed_for_ext:
        raise MimeRejected(
            f"Content type '{sniffed}' does not match extension '{ext}'."
        )
    if sniffed in _OOXML_ZIP and not _is_ooxml_container(data, ext):
        raise MimeRejected(
            f"File claims extension '{ext}' but is not a valid OOXML document."
        )
    return sniffed
