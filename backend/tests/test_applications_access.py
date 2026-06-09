"""Unit: Zugriffsauflösung A/P für Antrags-Endpunkte (T-12, api.md §1)."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

import pytest

from app.modules.applications.access import require_app_edit, require_app_read
from app.modules.auth.principal import Applicant, Principal
from app.shared.errors import ForbiddenError, UnauthorizedError


def _principal(*perms: str, sub: str = "p") -> Principal:
    return Principal(sub=sub, permissions=set(perms))


class _FakeDb:
    """Minimaler Session-Stub: ``scalar`` liefert das gesetzte ``created_by``."""

    def __init__(self, created_by: str | None = None) -> None:
        self._created_by = created_by

    async def scalar(self, *_a: Any, **_k: Any) -> str | None:
        return self._created_by


def test_read_principal_with_permission() -> None:
    app_id = uuid4()
    access = asyncio.run(require_app_read(app_id, _FakeDb(), _principal("application.read"), None))
    assert access.principal is not None
    assert access.can_see_internal is True
    assert access.author_kind == "principal"
    assert access.actor == "p"


def test_read_principal_without_permission_403() -> None:
    with pytest.raises(ForbiddenError):
        asyncio.run(require_app_read(uuid4(), _FakeDb(), _principal(), None))


def test_read_creator_without_permission_ok() -> None:
    """Eingeloggte:r Ersteller:in liest den eigenen Antrag ohne Permission (#24)."""
    app_id = uuid4()
    access = asyncio.run(
        require_app_read(app_id, _FakeDb(created_by="p"), _principal(sub="p"), None)
    )
    assert access.principal is not None and access.actor == "p"


def test_read_applicant_scoped_view() -> None:
    app_id = uuid4()
    applicant = Applicant(application_id=str(app_id), scope="view")
    access = asyncio.run(require_app_read(app_id, _FakeDb(), None, applicant))
    assert access.applicant is not None
    assert access.can_see_internal is False
    assert access.author_kind == "applicant"
    assert access.actor == "applicant"


def test_read_applicant_wrong_application_403() -> None:
    applicant = Applicant(application_id=str(uuid4()), scope="edit")
    with pytest.raises(ForbiddenError):
        asyncio.run(require_app_read(uuid4(), _FakeDb(), None, applicant))


def test_read_no_identity_401() -> None:
    with pytest.raises(UnauthorizedError):
        asyncio.run(require_app_read(uuid4(), _FakeDb(), None, None))


def test_edit_requires_manage_permission() -> None:
    app_id = uuid4()
    with pytest.raises(ForbiddenError):
        asyncio.run(require_app_edit(app_id, _FakeDb(), _principal("application.read"), None))
    access = asyncio.run(
        require_app_edit(app_id, _FakeDb(), _principal("application.manage"), None)
    )
    assert access.principal is not None


def test_edit_creator_without_permission_ok() -> None:
    """Ersteller:in darf den eigenen Antrag bearbeiten ohne ``application.manage`` (#24)."""
    app_id = uuid4()
    access = asyncio.run(
        require_app_edit(app_id, _FakeDb(created_by="p"), _principal(sub="p"), None)
    )
    assert access.principal is not None


def test_edit_non_creator_without_permission_403() -> None:
    app_id = uuid4()
    with pytest.raises(ForbiddenError):
        asyncio.run(
            require_app_edit(app_id, _FakeDb(created_by="someone-else"), _principal(sub="p"), None)
        )


def test_edit_applicant_view_scope_insufficient_403() -> None:
    app_id = uuid4()
    applicant = Applicant(application_id=str(app_id), scope="view")
    with pytest.raises(ForbiddenError):
        asyncio.run(require_app_edit(app_id, _FakeDb(), None, applicant))


def test_edit_applicant_edit_scope_ok() -> None:
    app_id = uuid4()
    applicant = Applicant(application_id=str(app_id), scope="edit")
    access = asyncio.run(require_app_edit(app_id, _FakeDb(), None, applicant))
    assert access.applicant is not None
