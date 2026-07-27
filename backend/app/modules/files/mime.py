"""MIME sniffing with libmagic and the type allowlist.

The content decides, not the extension. ``sniff_mime`` reads the magic header of the
bytes. ``validate_upload`` rejects a file when the sniffed type is not in the allowlist.
It also rejects a file when the sniffed type does not match the extension, with 415. So
``evil.exe`` cannot pose as ``foto.png``.

The module imports ``python-magic`` (libmagic) lazily. Only the paths that really take
uploads need the system library, that is the worker and the API runtime. Contract CI
does not need it.
"""

from __future__ import annotations

import io
import os
import zipfile

# The allowlist holds sniffed types, never the type that the client claims.
ALLOWED_MIME_TYPES: frozenset[str] = frozenset(
    {
        "application/pdf",
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        # Legacy Office and OOXML. libmagic sometimes sniffs OOXML as application/zip.
        # Zip is allowed only for .docx, .xlsx and .pptx, and only when the container
        # carries the OOXML structure. See _is_ooxml_container.
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

# An older libmagic often sniffs an OOXML container as ``application/zip``. The map
# accepts that type on purpose.
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

# The structural check uses this map when libmagic sniffs OOXML only as
# ``application/zip``. A real OOXML package holds ``[Content_Types].xml`` and the
# top-level directory of the format, that is word/, xl/ or ppt/. An arbitrary ZIP
# therefore cannot pose as an Office document.
_OOXML_REQUIRED_DIR: dict[str, str] = {
    ".docx": "word/",
    ".xlsx": "xl/",
    ".pptx": "ppt/",
}


class MimeRejected(Exception):
    """The file is not accepted: the type is not allowed or does not match the extension."""


def sniff_mime(data: bytes) -> str:
    """Return the MIME type that libmagic sniffs from the bytes.

    Empty input gives ``application/x-empty``.
    """
    if not data:
        return "application/x-empty"
    import magic  # lazy import: only the upload path needs libmagic

    return magic.from_buffer(data, mime=True)


def file_extension(filename: str | None) -> str:
    """Return the lowercased extension with the dot, or ``""`` when there is none."""
    if not filename:
        return ""
    return os.path.splitext(filename)[1].lower()


_FILENAME_SAFE = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._- "
)
_FILENAME_MAX = 200


def sanitize_filename(filename: str | None) -> str:
    """Harden a filename: drop the path components and replace special characters.

    This protects the ``storage_key`` against ``../`` traversal, NUL bytes and slashes.
    It also protects the stored display name. Every character outside the safe set
    becomes an underscore. The function caps the length. If nothing usable remains, it
    returns ``upload``.
    """
    raw = (filename or "").replace("\\", "/")
    base = os.path.basename(raw).strip()
    cleaned = "".join(c if c in _FILENAME_SAFE else "_" for c in base).strip(" .")
    cleaned = cleaned[:_FILENAME_MAX]
    return cleaned or "upload"


def _is_ooxml_container(data: bytes, ext: str) -> bool:
    """Tell whether ``data`` is a real OOXML package for ``ext``.

    The check needs a readable ZIP container with ``[Content_Types].xml`` and the
    top-level directory of the format (``word/``, ``xl/`` or ``ppt/``). It therefore
    rejects an arbitrary ZIP that poses as ``.docx``, ``.xlsx`` or ``.pptx``, even when
    libmagic sniffs the bytes only as ``application/zip``.
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
    """Validate the uploaded bytes and return the sniffed MIME type.

    The function applies three rules:

    1. The sniffed type must be in ``ALLOWED_MIME_TYPES``.
    2. The extension must be known and the sniffed type must match it. The content
       counts, not the claimed extension.
    3. If an OOXML upload sniffs only as ``application/zip`` (older libmagic), the ZIP
       container must also carry the OOXML structure. That structure is
       ``[Content_Types].xml`` and one of ``word/``, ``xl/`` or ``ppt/``. Every other
       ZIP counts as an arbitrary ZIP and the function rejects it.

    Returns:
        The sniffed MIME type.

    Raises:
        MimeRejected: The file breaks one of the three rules.
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
