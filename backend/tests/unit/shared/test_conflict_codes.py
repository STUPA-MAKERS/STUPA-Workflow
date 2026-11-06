"""Every ``ConflictError`` in ``app/`` names its own ``code`` (§S/shared/api/000042).

Without ``code=`` the error answers with the generic ``conflict``, and a client cannot
tell one 409 from another.
"""

from __future__ import annotations

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[3] / "app"


def _conflicts_without_code() -> list[str]:
    """Return ``path:line`` of each ``ConflictError(...)`` call without ``code=``."""
    return [
        f"{path.relative_to(APP.parent)}:{node.lineno}"
        for path in sorted(APP.rglob("*.py"))
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", getattr(node.func, "attr", None)) == "ConflictError"
        and not any(keyword.arg == "code" for keyword in node.keywords)
    ]


def _generic_conflict_codes() -> list[str]:
    """Return ``path:line`` of each ``ConflictError(..., code="conflict")`` call."""
    return [
        f"{path.relative_to(APP.parent)}:{node.lineno}"
        for path in sorted(APP.rglob("*.py"))
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", getattr(node.func, "attr", None)) == "ConflictError"
        and any(
            keyword.arg == "code"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value == "conflict"
            for keyword in node.keywords
        )
    ]


def test_every_conflict_error_passes_a_code() -> None:
    """No ``ConflictError`` call in ``app/`` relies on the generic default code."""
    assert _conflicts_without_code() == []


def test_no_conflict_error_uses_the_generic_code() -> None:
    """§S/shared/api/000468: every ``ConflictError`` names a specific code."""
    assert _generic_conflict_codes() == []
