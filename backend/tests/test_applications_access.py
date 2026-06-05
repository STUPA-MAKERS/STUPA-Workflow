"""Unit: Zugriffsauflösung A/P für Antrags-Endpunkte (T-12, api.md §1)."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from app.modules.applications.access import require_app_edit, require_app_read
from app.modules.auth.principal import Applicant, Principal
from app.shared.errors import ForbiddenError, UnauthorizedError


def _principal(*perms: str) -> Principal:
    return Principal(sub="p", permissions=set(perms))


def test_read_principal_with_permission() -> None:
    app_id = uuid4()
    access = asyncio.run(require_app_read(app_id, _principal("application.read"), None))
    assert access.principal is not None
    assert access.can_see_internal is True
    assert access.author_kind == "principal"
    assert access.actor == "p"


def test_read_principal_without_permission_403() -> None:
    with pytest.raises(ForbiddenError):
        asyncio.run(require_app_read(uuid4(), _principal(), None))


def test_read_applicant_scoped_view() -> None:
    app_id = uuid4()
    applicant = Applicant(application_id=str(app_id), scope="view")
    access = asyncio.run(require_app_read(app_id, None, applicant))
    assert access.applicant is not None
    assert access.can_see_internal is False
    assert access.author_kind == "applicant"
    assert access.actor == "applicant"


def test_read_applicant_wrong_application_403() -> None:
    applicant = Applicant(application_id=str(uuid4()), scope="edit")
    with pytest.raises(ForbiddenError):
        asyncio.run(require_app_read(uuid4(), None, applicant))


def test_read_no_identity_401() -> None:
    with pytest.raises(UnauthorizedError):
        asyncio.run(require_app_read(uuid4(), None, None))


def test_edit_requires_manage_permission() -> None:
    app_id = uuid4()
    with pytest.raises(ForbiddenError):
        asyncio.run(require_app_edit(app_id, _principal("application.read"), None))
    access = asyncio.run(require_app_edit(app_id, _principal("application.manage"), None))
    assert access.principal is not None


def test_edit_applicant_view_scope_insufficient_403() -> None:
    app_id = uuid4()
    applicant = Applicant(application_id=str(app_id), scope="view")
    with pytest.raises(ForbiddenError):
        asyncio.run(require_app_edit(app_id, None, applicant))


def test_edit_applicant_edit_scope_ok() -> None:
    app_id = uuid4()
    applicant = Applicant(application_id=str(app_id), scope="edit")
    access = asyncio.run(require_app_edit(app_id, None, applicant))
    assert access.applicant is not None
