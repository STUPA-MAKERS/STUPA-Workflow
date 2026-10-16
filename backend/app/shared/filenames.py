"""File names of uploads: the display name, the storage-key name and the download header.

An upload has two names, and they have different rules:

* The **display name** is what the user sees in a list and what the browser saves the
  download as. It keeps every printable Unicode character (umlauts, CJK, emoji), so
  ``Einführung.pdf`` stays ``Einführung.pdf``. ``sanitize_display_name`` normalizes it
  to NFC and removes what can hurt: path components, control characters, the bidi
  override and isolate characters (an ``U+202E`` makes ``gpj.exe`` look like
  ``exe.jpg``), every other invisible format character (Unicode category Cf) and the
  zero-width characters.
* The **storage-key name** is the last segment of the MinIO object key. It stays ASCII
  (``sanitize_storage_name``), because an object key is a path: it must never hold a
  separator, a ``..`` or a byte that a tool along the way encodes differently.

``content_disposition`` builds the ``Content-Disposition`` header from a display name.
Starlette encodes a header value as Latin-1, so a ``€`` or an emoji in a plain
``filename="…"`` raises ``UnicodeEncodeError`` and the response fails with 500. The
header therefore carries an ASCII ``filename`` fallback plus the exact name as
``filename*=UTF-8''<percent-encoded>`` (RFC 6266, RFC 5987). The value is pure ASCII
and holds no quote, backslash, CR or LF, so it cannot inject a header.
"""

from __future__ import annotations

import os
import unicodedata
from typing import Literal
from urllib.parse import quote

DISPLAY_NAME_MAX = 200
"""The longest display name in characters. A longer name is cut and keeps its extension."""

STORAGE_NAME_MAX = 200
"""The longest storage-key name in characters."""

DEFAULT_NAME = "upload"
"""The name when nothing usable remains of the given one."""

_EXTENSION_MAX = 16
"""An extension longer than this is not kept when the name is cut."""

_JOINERS = frozenset("‌‍")
"""ZWNJ and ZWJ. Emoji sequences and several scripts need them between two visible
characters. At an edge or next to a dot or a space they only hide something."""

_STORAGE_SAFE = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._- "
)

_FALLBACK_UNSAFE = frozenset('"\\%;/')
"""ASCII characters that do not go into the quoted ``filename`` fallback. A quote or a
backslash would end or escape the quoted string; some browsers decode ``%`` sequences
in it, ``;`` confuses lenient parsers, and a ``/`` can come back from the ASCII fold of
a fullwidth solidus (``U+FF0F``)."""


def _basename(name: str) -> str:
    """Return the last path component, for both ``/`` and ``\\`` separators."""
    return os.path.basename(name.replace("\\", "/"))


def _drop_char(char: str) -> bool:
    """Tell whether a character never belongs in a display name.

    The categories are Cc (control, also CR, LF, TAB and NUL), Cs (a lone surrogate,
    which Postgres cannot store), Zl and Zp (line and paragraph separators) and Cf
    (format). Cf is invisible: it holds the bidi embeddings, overrides and isolates
    (U+202A to U+202E, U+2066 to U+2069), the bidi marks LRM, RLM and ALM, the
    zero-width space, the word joiner, the BOM, the soft hyphen, the invisible
    operators and the tag characters. A bidi control reorders the text around it and
    so can fake an extension, and the tag characters hide text from a person but not
    from a model that reads the name through MCP. ZWJ and ZWNJ are Cf too, but they
    stay here, because ``_drop_loose_joiners`` decides about them.
    """
    if char in _JOINERS:
        return False
    return unicodedata.category(char) in {"Cc", "Cs", "Zl", "Zp", "Cf"}


def _drop_loose_joiners(name: str) -> str:
    """Remove a ZWJ or ZWNJ that does not sit between two visible characters."""
    out: list[str] = []
    for i, char in enumerate(name):
        if char in _JOINERS:
            before = name[i - 1] if i > 0 else ""
            after = name[i + 1] if i + 1 < len(name) else ""
            if not before or not after or {before, after} & set(" ."):
                continue
            if before in _JOINERS or after in _JOINERS:
                continue
        out.append(char)
    return "".join(out)


def _trim(name: str) -> str:
    """Strip spaces and dots at both ends, and joiners that the strip exposed."""
    previous = None
    while previous != name:
        previous = name
        name = _drop_loose_joiners(name.strip(" ."))
    return name


def _cap(name: str, limit: int) -> str:
    """Cut ``name`` to ``limit`` characters and keep a short extension."""
    if len(name) <= limit:
        return name
    stem, ext = os.path.splitext(name)
    if not stem or len(ext) > _EXTENSION_MAX:
        return name[:limit]
    return stem[: limit - len(ext)] + ext


def sanitize_display_name(filename: str | None, *, default: str = DEFAULT_NAME) -> str:
    """Clean a client file name for display and download, and keep its Unicode.

    The steps are: NFC normalization, the last path component only, every space
    character as a plain space, no control, surrogate, line-separator, format (Cf,
    which includes the bidi controls) or zero-width character, no space or dot at an
    edge, at most ``DISPLAY_NAME_MAX`` characters with the extension kept.

    Args:
        filename: The name the client sent, or ``None``.
        default: The name when nothing usable remains.

    Returns:
        The display name. It never holds ``/`` or ``\\`` and is never ``.`` or ``..``.
    """
    raw = unicodedata.normalize("NFC", filename or "")
    chars = (
        " " if unicodedata.category(c) == "Zs" else c for c in raw if not _drop_char(c)
    )
    name = _trim(_basename("".join(chars)))
    name = _trim(_cap(name, DISPLAY_NAME_MAX))
    return name or default


def _ascii_fold(name: str) -> str:
    """Decompose accented letters and drop the marks, so ``ü`` becomes ``u``."""
    decomposed = unicodedata.normalize("NFKD", name)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def sanitize_storage_name(filename: str | None) -> str:
    """Build the ASCII name for the last segment of an object key.

    The name keeps only ``[A-Za-z0-9._- ]``. An accented letter loses its accent, every
    other character becomes ``_``. It drops the path components first, so ``../`` and
    a NUL byte never reach the key. The function caps the length. If nothing usable
    remains, it returns ``upload``.
    """
    base = _basename(_ascii_fold(filename or "")).strip()
    cleaned = "".join(c if c in _STORAGE_SAFE else "_" for c in base).strip(" .")
    cleaned = _cap(cleaned, STORAGE_NAME_MAX).strip(" .")
    return cleaned or DEFAULT_NAME


def _ascii_fallback(name: str) -> str:
    """Build the plain ``filename`` value: printable ASCII, no quote, no backslash.

    The value is capped like the display name, because the NFKD fold can make one
    character into many (``U+FDFA`` gives 18). Without the cap a name of 200 such
    characters gives a header of more than 5 KB, and nginx answers 502 when the
    response headers do not fit its ``proxy_buffer_size`` of 4 KB.
    """
    folded = _ascii_fold(name)
    fallback = "".join(
        c if " " <= c <= "~" and c not in _FALLBACK_UNSAFE else "_" for c in folded
    )
    return _cap(fallback, DISPLAY_NAME_MAX) or "download"


def content_disposition(
    kind: Literal["attachment", "inline"], filename: str, *, default: str = "download"
) -> str:
    """Build a ``Content-Disposition`` value that is safe for any file name.

    The name runs through ``sanitize_display_name`` first, so a stored name from before
    this rule (or from a client field) cannot bring a CR, LF or bidi control into the
    header. The value then names the file twice: ``filename="<ASCII fallback>"`` for an
    old client and ``filename*=UTF-8''<percent-encoded>`` with the exact name. A client
    that knows RFC 6266 uses the second one.

    Args:
        kind: ``attachment`` forces a download, ``inline`` lets the browser render.
        filename: The display name of the file.
        default: The name when nothing usable remains of ``filename``.

    Returns:
        An ASCII header value. ``Einführung €.pdf`` gives
        ``attachment; filename="Einfuhrung _.pdf";
        filename*=UTF-8''Einf%C3%BChrung%20%E2%82%AC.pdf`` (one line).
    """
    name = sanitize_display_name(filename, default=default)
    return (
        f'{kind}; filename="{_ascii_fallback(name)}"; '
        f"filename*=UTF-8''{quote(name, safe='')}"
    )
