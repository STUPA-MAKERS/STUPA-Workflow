"""An applicant session has no scope.

`get_current_applicant` binds every valid session to its application. Each action
checks the current state.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app import deps
from app.settings import load_settings

#: A placeholder request and session. The function does not read them; the patched helpers do.
_ANY: Any = SimpleNamespace()


def _settings() -> Any:
    return load_settings(
        database_url="postgresql+asyncpg://x/y",
        session_secret="sess-secret-0123456",
        magic_link_secret="ml-pepper-0123456",
    )


async def test_valid_session_gives_the_bound_applicant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _load(*_a: Any, **_k: Any) -> Any:
        return SimpleNamespace(application_id="aid-1", email=None)

    monkeypatch.setattr(deps, "_bearer_token", lambda *_a: "sid")
    monkeypatch.setattr(deps.sessions, "load_applicant_session", _load)
    applicant = await deps.get_current_applicant(
        _ANY,
        _ANY,
        _settings(),
    )
    assert applicant is not None
    assert applicant.application_id == "aid-1"


async def test_missing_session_gives_no_applicant(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _load(*_a: Any, **_k: Any) -> Any:
        return None

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
