"""A10: a role key matches ``^[a-z][a-z0-9_]*$`` (global role and gremium role).

The schemas reject a bad key with a ``ValidationError``. The API turns it into 422
problem+json before any service call. The update schemas carry no key at all.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.deps import Principal, get_current_principal
from app.main import create_app
from app.modules.admin.router import get_config_service, get_gremium_role_service
from app.modules.admin.schemas import (
    ROLE_KEY_PATTERN,
    GremiumRoleCreate,
    GremiumRoleUpdate,
    RoleCreate,
    RoleUpdate,
)

_GOOD = ["admin", "vorstand", "manager", "kasse_2", "a", "finanz_referat"]
_BAD = [
    "",
    "Admin",
    "ADMIN",
    "2nd",
    "_hidden",
    "role-x",
    "role.x",
    "role x",
    "rolle_ä",
    "admin\n",
]


def test_pattern_is_the_documented_one() -> None:
    assert ROLE_KEY_PATTERN == r"^[a-z][a-z0-9_]*$"


@pytest.mark.parametrize("key", _GOOD)
def test_good_keys_pass(key: str) -> None:
    assert RoleCreate(key=key).key == key
    assert GremiumRoleCreate(key=key).key == key


@pytest.mark.parametrize("key", _BAD)
def test_bad_global_role_key_is_rejected(key: str) -> None:
    with pytest.raises(ValidationError):
        RoleCreate(key=key)


@pytest.mark.parametrize("key", _BAD)
def test_bad_gremium_role_key_is_rejected(key: str) -> None:
    with pytest.raises(ValidationError):
        GremiumRoleCreate(key=key)


def test_updates_carry_no_key() -> None:
    assert "key" not in RoleUpdate.model_fields
    assert "key" not in GremiumRoleUpdate.model_fields


class _NoService:
    """Fails the test when the route reaches the service despite a bad key."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"service.{name} must not run for an invalid key")


@pytest.fixture
def client() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_config_service] = _NoService
    app.dependency_overrides[get_gremium_role_service] = _NoService
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        sub="admin", permissions={"admin.roles", "admin.gremium_roles", "admin.gremien"}
    )
    return TestClient(app)


def test_api_rejects_a_bad_global_role_key(client: TestClient) -> None:
    r = client.post("/api/admin/roles", json={"key": "Kasse-1", "label": {}, "permissions": []})
    assert r.status_code == 422
    assert r.headers["content-type"].startswith("application/problem+json")


def test_api_rejects_a_bad_gremium_role_key(client: TestClient) -> None:
    r = client.post(f"/api/admin/gremien/{uuid4()}/roles", json={"key": "Schrift Führung"})
    assert r.status_code == 422
    assert r.headers["content-type"].startswith("application/problem+json")
