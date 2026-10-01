"""An applicant session has no fixed scope (O4, F5).

`get_current_applicant` gives every valid session the scope `edit`, also an old
`view` session from before that change. Each action checks the current state.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app import deps
from app.settings import load_settings

# The function reads neither the request nor the session itself: the patched
# helpers take them.
_ANY: Any = SimpleNamespace()


def _settings() -> Any:
    return load_settings(
        database_url="postgresql+asyncpg://x/y",
        session_secret="sess-secret-0123456",
        magic_link_secret="ml-pepper-0123456",
    )


@pytest.mark.parametrize("stored", ["edit", "view"])
async def test_every_valid_session_acts_as_edit(
    monkeypatch: pytest.MonkeyPatch, stored: str
) -> None:
    async def _load(*_a: Any, **_k: Any) -> Any:
        return SimpleNamespace(scope=stored, application_id="aid-1")

    monkeypatch.setattr(deps, "_bearer_token", lambda *_a: "sid")
    monkeypatch.setattr(deps.sessions, "load_applicant_session", _load)
    applicant = await deps.get_current_applicant(
        _ANY,
        _ANY,
        _settings(),
    )
    assert applicant is not None
    assert (applicant.application_id, applicant.scope) == ("aid-1", "edit")


async def test_unknown_scope_gives_no_applicant(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _load(*_a: Any, **_k: Any) -> Any:
        return SimpleNamespace(scope="admin", application_id="aid-1")

    monkeypatch.setattr(deps, "_bearer_token", lambda *_a: "sid")
    monkeypatch.setattr(deps.sessions, "load_applicant_session", _load)
    assert (
        await deps.get_current_applicant(
            _ANY,
            _ANY,
            _settings(),
        )
        is None
    )
