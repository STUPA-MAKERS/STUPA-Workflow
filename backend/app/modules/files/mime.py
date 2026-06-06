"""MIME-Sniffing (libmagic) + Typ-Allowlist (security.md §6).

Der **Inhalt** entscheidet, nicht die Endung: ``sniff_mime`` liest den Magic-Header der
Bytes. ``validate_upload`` lehnt ab, wenn der gesniffte Typ nicht in der Allowlist liegt
**oder** nicht zur Datei-Endung passt (Sniff ≠ Endung → 415). So lässt sich eine
``evil.exe`` nicht als ``foto.png`` tarnen.

``python-magic`` (libmagic) wird **lazy** importiert — die System-Lib muss nur dort
vorhanden sein, wo wirklich hochgeladen wird (Worker/API-Runtime), nicht im Contract-CI.
"""

from __future__ import annotations

import os

# Erlaubte gesniffte MIME-Typen (PDF / Bild / Office), security.md §6.
ALLOWED_MIME_TYPES: frozenset[str] = frozenset(
    {
        "application/pdf",
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        # Office (alt + OOXML). OOXML wird von libmagic teils als application/zip
        # erkannt → zip ist (nur) bei .docx/.xlsx/.pptx zulässig (siehe _EXT_TO_MIME:
        # ein als .pdf getarntes Zip fliegt am Endungs-Abgleich raus).
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

# Endung → akzeptable gesniffte MIME-Typen. OOXML-Container sniffen oft als
# ``application/zip`` (älteres libmagic) → bewusst mit zugelassen.
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


class MimeRejected(Exception):
    """Datei nicht akzeptiert (nicht erlaubter Typ oder Sniff ≠ Endung)."""


def sniff_mime(data: bytes) -> str:
    """Gesniffter MIME-Typ der Bytes (libmagic). Leerer Input → ``application/x-empty``."""
    if not data:
        return "application/x-empty"
    import magic  # lazy: libmagic nur auf dem Upload-Pfad nötig

    return magic.from_buffer(data, mime=True)


def file_extension(filename: str | None) -> str:
    """Kleingeschriebene Endung inkl. Punkt (``""`` wenn keine)."""
    if not filename:
        return ""
    return os.path.splitext(filename)[1].lower()


# Erlaubte Zeichen im gespeicherten Dateinamen (alles andere → ``_``).
_FILENAME_SAFE = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._- "
)
_FILENAME_MAX = 200


def sanitize_filename(filename: str | None) -> str:
    """Dateinamen härten: Pfadanteile entfernen, Control-/Sonderzeichen ersetzen.

    Schützt sowohl den ``storage_key`` (kein ``../``-Traversal, keine NUL/Slashes) als
    auch den gespeicherten Anzeigenamen. Fällt auf ``upload`` zurück, wenn nach der
    Bereinigung nichts Brauchbares übrig bleibt; begrenzt die Länge."""
    raw = (filename or "").replace("\\", "/")
    base = os.path.basename(raw).strip()  # Pfadanteile (inkl. ``../``) verwerfen
    cleaned = "".join(c if c in _FILENAME_SAFE else "_" for c in base).strip(" .")
    cleaned = cleaned[:_FILENAME_MAX]
    return cleaned or "upload"


def validate_upload(filename: str | None, data: bytes) -> str:
    """Bytes prüfen → gesniffter MIME-Typ, oder :class:`MimeRejected`.

    Regeln (security.md §6):

    1. Gesniffter Typ muss in :data:`ALLOWED_MIME_TYPES` liegen.
    2. Endung muss bekannt sein **und** der gesniffte Typ zu ihr passen (Sniff ≠ Endung
       → Ablehnung). So zählt der Inhalt, nicht die behauptete Endung.
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
    return sniffed
