"""No text that a person sees names the platform with a fixed old product name.

Rule: §F/administration/admin/001230. The app names the platform by the branding. Where the
branding cannot reach, the built-in name is "STUPA Workflow".
"""

from __future__ import annotations

import re
from pathlib import Path

#: From tests/unit/, parents[3] is the repo root.
_ROOT = Path(__file__).resolve().parents[3]

#: The sources of every text that a person sees: the frontend, the backend, the MCP server
#: and the PDF render service. Tests are left out, because they may name the old text to
#: prove that it is gone.
_SOURCES = (
    "frontend/src",
    "frontend/public",
    "backend/app",
    "mcp/antragsplattform_mcp",
    "typst/typst_service",
    "typst/template",
)

_SUFFIXES = {".ts", ".html", ".json", ".webmanifest", ".py", ".j2", ".typ", ".md", ".txt"}

#: The old product name. The lower-case package and client names (``antragsplattform-mcp``,
#: ``antragsplattform_mcp``, ``ANTRAGSPLATTFORM_URL``) stay, because existing installations
#: use them (§F/integrations/mcp/001232).
_OLD_NAME = re.compile(r"Antragsplattform|[Aa]pplication [Pp]latform")


def _files() -> list[Path]:
    found: list[Path] = []
    for source in _SOURCES:
        base = _ROOT / source
        if not base.is_dir():
            continue
        found.extend(
            path
            for path in base.rglob("*")
            if path.is_file()
            and path.suffix in _SUFFIXES
            and "tests" not in path.relative_to(base).parts
            and "node_modules" not in path.parts
            and not path.name.endswith(".spec.ts")
        )
    return found


def test_no_visible_text_names_the_old_product_name() -> None:
    hits = [
        f"{path.relative_to(_ROOT)}:{number}"
        for path in _files()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if _OLD_NAME.search(line)
    ]
    assert hits == []


def test_the_sources_exist() -> None:
    assert (_ROOT / "frontend/src/app/core/i18n/catalog/de.json").is_file()
    assert len(_files()) > 100
