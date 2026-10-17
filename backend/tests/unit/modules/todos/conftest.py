"""Shared fixtures of the to-do unit tests."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any

import pytest

from app.modules.todos import service as svc_mod
from app.shared.people import PersonRef


@pytest.fixture(autouse=True)
def people(monkeypatch: pytest.MonkeyPatch) -> dict[uuid.UUID, PersonRef]:
    """``person_refs`` without a query: a test fills the returned map."""
    known: dict[uuid.UUID, PersonRef] = {}

    async def _refs(_session: Any, ids: Iterable[uuid.UUID | None]) -> dict[uuid.UUID, PersonRef]:
        return {pid: known[pid] for pid in ids if pid is not None and pid in known}

    monkeypatch.setattr(svc_mod, "person_refs", _refs)
    return known
