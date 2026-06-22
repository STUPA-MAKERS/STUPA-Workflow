"""Guard against the pytex-preprocessor pin diverging between the two manifests.

The Docker image installs ``requirements.txt`` while local dev / tooling reads
``pyproject.toml``; if the two ``pytex-preprocessor==`` pins drift, dev/CI and
prod can resolve different versions of a security-sensitive Markdown→PDF
renderer (AUD-052). This test fails fast on that divergence.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

_PYTEX_DIR = Path(__file__).resolve().parent.parent
_PKG = "pytex-preprocessor"
_PIN_RE = re.compile(rf"^{re.escape(_PKG)}==(?P<v>[^\s#]+)", re.MULTILINE)


def _pyproject_pin() -> str:
    data = tomllib.loads((_PYTEX_DIR / "pyproject.toml").read_text(encoding="utf-8"))
    deps: list[str] = data["project"]["dependencies"]
    pins = [d for d in deps if d.replace(" ", "").startswith(f"{_PKG}==")]
    assert len(pins) == 1, f"expected exactly one {_PKG} pin in pyproject, got {pins}"
    return pins[0].split("==", 1)[1].strip()


def _requirements_pin() -> str:
    text = (_PYTEX_DIR / "requirements.txt").read_text(encoding="utf-8")
    matches = _PIN_RE.findall(text)
    assert len(matches) == 1, f"expected exactly one {_PKG}== pin in requirements, got {matches}"
    return matches[0].strip()


def test_pytex_preprocessor_pin_matches_across_manifests() -> None:
    assert _pyproject_pin() == _requirements_pin(), (
        "pytex-preprocessor pin diverges between pyproject.toml and requirements.txt; "
        "keep both in lockstep so dev/CI and the deployed image resolve the same renderer"
    )
