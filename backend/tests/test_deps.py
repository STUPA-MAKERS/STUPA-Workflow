"""TDD: DI-Stubs (deps.py). Skelett — echte Auth in T-10."""

import pytest

from app.deps import (
    Applicant,
    Principal,
    get_current_applicant,
    get_current_principal,
    require_applicant,
    require_principal,
)
from app.shared.errors import ForbiddenError, UnauthorizedError


def test_principal_dataclass_has_permission() -> None:
    p = Principal(sub="u1", roles=["admin"], permissions={"admin.config"}, groups=set())
    assert p.has("admin.config")
    assert not p.has("vote.cast")


def test_applicant_dataclass() -> None:
    a = Applicant(application_id="app-1", scope="edit")
    assert a.application_id == "app-1"
    assert a.scope == "edit"


def test_get_current_principal_stub_none() -> None:
    # Skelett: keine Session-Auflösung → None.
    assert get_current_principal() is None


def test_require_principal_no_session_unauthorized() -> None:
    dep = require_principal("application.read")
    with pytest.raises(UnauthorizedError):
        dep(principal=None)


def test_require_principal_missing_perm_forbidden() -> None:
    dep = require_principal("admin.config")
    p = Principal(sub="u1", roles=[], permissions={"application.read"}, groups=set())
    with pytest.raises(ForbiddenError):
        dep(principal=p)


def test_require_principal_ok_returns_principal() -> None:
    dep = require_principal("application.read")
    p = Principal(sub="u1", roles=[], permissions={"application.read"}, groups=set())
    assert dep(principal=p) is p


def test_get_current_applicant_stub_none() -> None:
    assert get_current_applicant() is None


def test_require_applicant_stub_unauthorized() -> None:
    dep = require_applicant("edit")
    with pytest.raises(UnauthorizedError):
        dep(applicant=None)
