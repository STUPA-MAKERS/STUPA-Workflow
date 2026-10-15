"""The builtin CD logos as package data, for their conversion into uploads.

A ``cd_variant_logo`` row with ``vendored_name`` points at one of nine logos
that the typst render service ships (map ``vendored-logos`` in
``typst/template/protocol.typ``, files in the submodule
``typst/vendor/hsrtreport-typst``). This package holds copies of the same nine
SVG files. The worker job ``migrate_builtin_cd_logos`` uploads them into the
object storage and turns each vendored row into a normal upload, so an admin can
download, replace and delete them like any other logo.

``BUILTIN_LOGOS`` maps each name of ``VENDORED_LOGO_NAMES`` to its file and pins
the SHA-256 of every file. A test compares the files
against it, and against the submodule when it is checked out, so a changed or
stale copy is visible in the review.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from importlib import resources
from typing import Final


@dataclass(frozen=True, slots=True)
class BuiltinLogo:
    """One bundled logo file.

    Attributes:
        file_name: The file name in this package. It is also the file name that
            the converted row shows, for example ``STUPA.svg``.
        sha256: The hex SHA-256 of the file bytes.
    """

    file_name: str
    sha256: str


BUILTIN_LOGO_MIME: Final[str] = "image/svg+xml"

BUILTIN_LOGOS: Final[dict[str, BuiltinLogo]] = {
    "HSRT": BuiltinLogo(
        "HSRT.svg", "e989d4d93f3916c0c8df1baf2dfeaba009b30961424e655646252cdc667c1207"
    ),
    "INF": BuiltinLogo(
        "INF.svg", "5de349484af2c3bb470dc43876ce3f93a3a7e9fe00f3314358a1304ef3f4effd"
    ),
    "ASTA": BuiltinLogo(
        "ASTA.svg", "ff0ff7d9dee6b358168279ab1c35bb75cfdd706a102a0597beecbdf903d62d42"
    ),
    "STUPA": BuiltinLogo(
        "STUPA.svg", "ea552ecb7570476b502d2341b220e3844284afce5ce186b0056c838933c24da5"
    ),
    "ECHO": BuiltinLogo(
        "ECHO.svg", "8fc8a87bd80a908be4fed9c24fdb51fd9681a8ae6e696ca03da14b522fc8f530"
    ),
    "MAKERS": BuiltinLogo(
        "MAKERS.svg", "30754628b602f90af39fbfc6c038b7a9044e875c876aca9b9b510a720c3740af"
    ),
    "MAKERS-RAlign": BuiltinLogo(
        "MAKERS-RAlign.svg", "6c82197d2ef7282034d76bf1c3f9895c2934b9305515a1f8c8764ce11e6b7124"
    ),
    "MAKERS-Icon": BuiltinLogo(
        "MAKERS-Icon.svg", "001914a3281abc8821de00672ba99de3d6621921132cbfd2aa3f19e1a4dfa8cb"
    ),
    "Skyline": BuiltinLogo(
        "Skyline.svg", "8a2fbc40f47f1fa278e98a33c0b8387948dd41f19d94ff30d69afb602456a2ea"
    ),
}


class BuiltinLogoMismatchError(RuntimeError):
    """A bundled file does not match the SHA-256 in ``BUILTIN_LOGOS``."""


def builtin_logo_bytes(name: str) -> tuple[BuiltinLogo, bytes] | None:
    """Load a bundled logo and check its SHA-256.

    Args:
        name: The ``vendored_name`` of a row.

    Returns:
        The manifest entry and the file bytes, or ``None`` for a name that the
        manifest does not hold.

    Raises:
        BuiltinLogoMismatchError: The file differs from the pinned hash. The
            conversion must not upload a file that nobody reviewed.
    """
    entry = BUILTIN_LOGOS.get(name)
    if entry is None:
        return None
    data = resources.files(__name__).joinpath(entry.file_name).read_bytes()
    if hashlib.sha256(data).hexdigest() != entry.sha256:
        raise BuiltinLogoMismatchError(f"bundled logo {entry.file_name} changed")
    return entry, data
