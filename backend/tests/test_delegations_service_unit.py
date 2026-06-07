"""TDD: DelegationService (T-45) — Config-Gate, Fenster, RBAC, Audit, Widerruf.

Jede Service-Verzweigung wird über einen Ergebnis-Queue-Fake (``flow_fakes``)
deterministisch getroffen — keine echte DB. Die DB-Constraints/timestamptz-Semantik
liegen in der Integration.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from app.modules.auth.models import RoleAssignment
from app.modules.auth.principal import Principal
from app.modules.delegations import service as delegations_service
from app.modules.delegations.schemas import DelegationCreate
from app.modules.delegations.service import (
    DelegationService,
    _to_utc,
    has_active_voting_delegation,
)
from app.settings import load_settings
from app.shared.errors import ForbiddenError, NotFoundError, ValidationProblem
from tests.flow_fakes import fake_session, result

NOW = datetime(2026, 6, 6, 12, 0, tzinfo=UTC)
FUTURE = datetime(2099, 1, 1, tzinfo=UTC)


def _settings(*, voting: bool = False) -> Any:
    return load_settings(delegation_voting_enabled=voting)


def _actor(
    sub: str = "deleg",
    roles: list[str] | None = None,
    perms: set[str] | None = None,
) -> Principal:
    return Principal(sub=sub, roles=roles or ["member"], permissions=perms or set())


def _payload(**over: Any) -> DelegationCreate:
    base: dict[str, Any] = {
        "principal_id": uuid4(),
        "role_id": uuid4(),
        "valid_until": FUTURE,
        "delegate_voting": False,
    }
    base.update(over)
    return DelegationCreate(**base)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def test_to_utc_normalizes() -> None:
    assert _to_utc(None) is None
    naive = datetime(2026, 6, 6, 12, 0)
    assert _to_utc(naive) == datetime(2026, 6, 6, 12, 0, tzinfo=UTC)
    aware = datetime(2026, 6, 6, 14, 0, tzinfo=UTC)
    assert _to_utc(aware) == aware


async def test_has_active_voting_delegation_scopes() -> None:
    # global scope (None), gültige Gremium-UUID, Nicht-UUID — alle drei Branches.
    db = fake_session(result(SimpleNamespace(id=uuid4())), result(), result())
    assert await has_active_voting_delegation(db, "deleg", None, NOW) is True
    assert await has_active_voting_delegation(db, "deleg", str(uuid4()), NOW) is False
    assert await has_active_voting_delegation(db, "deleg", "not-a-uuid", NOW) is False


# --------------------------------------------------------------------------- #
# create
# --------------------------------------------------------------------------- #
async def test_create_persists_and_audits() -> None:
    db = fake_session(
        result(SimpleNamespace(id=uuid4(), sub="other")),  # delegate exists
        result(SimpleNamespace(key="member")),  # role exists + held
        result(),  # audit advisory lock
        result(),  # audit prev-hash
    )
    out = await DelegationService(db, _settings()).create(_payload(), _actor())
    assert out.delegated_by == "deleg"
    assert out.granted_by == "deleg"
    assert out.active is True
    assert db.committed == 1
    persisted = [a for a in db.added if isinstance(a, RoleAssignment)]
    assert len(persisted) == 1
    assert persisted[0].delegated_by == "deleg"
    # Audit-Eintrag je Delegation.
    assert any(type(a).__name__ == "AuditEntry" for a in db.added)


async def test_create_voting_disabled_is_422() -> None:
    db = fake_session()
    with pytest.raises(ValidationProblem) as ei:
        await DelegationService(db, _settings(voting=False)).create(
            _payload(delegate_voting=True), _actor()
        )
    assert ei.value.status == 422
    assert db.committed == 0


async def test_create_voting_enabled_ok() -> None:
    db = fake_session(
        result(SimpleNamespace(id=uuid4(), sub="other")),
        result(SimpleNamespace(key="member")),
        result(),
        result(),
    )
    out = await DelegationService(db, _settings(voting=True)).create(
        _payload(delegate_voting=True), _actor()
    )
    assert out.delegate_voting is True


async def test_create_validuntil_in_past_is_422() -> None:
    db = fake_session()
    past = NOW - timedelta(days=3650)  # weit in der Vergangenheit
    with pytest.raises(ValidationProblem):
        await DelegationService(db, _settings()).create(
            _payload(valid_until=past), _actor()
        )


async def test_create_window_fully_elapsed_is_422() -> None:
    # validFrom < validUntil (erste Prüfung passiert), aber validUntil < now → 422.
    db = fake_session()
    start = NOW - timedelta(days=3650)
    end = NOW - timedelta(days=3640)
    with pytest.raises(ValidationProblem, match="elapsed"):
        await DelegationService(db, _settings()).create(
            _payload(valid_from=start, valid_until=end), _actor()
        )


async def test_create_validuntil_before_from_is_422() -> None:
    db = fake_session()
    with pytest.raises(ValidationProblem):
        await DelegationService(db, _settings()).create(
            _payload(valid_from=FUTURE, valid_until=FUTURE - timedelta(days=1)), _actor()
        )


async def test_create_unknown_principal_is_404() -> None:
    db = fake_session(result())  # delegate not found
    with pytest.raises(NotFoundError):
        await DelegationService(db, _settings()).create(_payload(), _actor())


async def test_create_self_delegation_is_422() -> None:
    db = fake_session(result(SimpleNamespace(id=uuid4(), sub="deleg")))  # same sub
    with pytest.raises(ValidationProblem):
        await DelegationService(db, _settings()).create(_payload(), _actor(sub="deleg"))


async def test_create_unknown_role_is_404() -> None:
    db = fake_session(
        result(SimpleNamespace(id=uuid4(), sub="other")),
        result(),  # role not found
    )
    with pytest.raises(NotFoundError):
        await DelegationService(db, _settings()).create(_payload(), _actor())


async def test_create_role_not_held_is_403() -> None:
    db = fake_session(
        result(SimpleNamespace(id=uuid4(), sub="other")),
        result(SimpleNamespace(key="admin")),  # actor holds only "member"
    )
    with pytest.raises(ForbiddenError):
        await DelegationService(db, _settings()).create(_payload(), _actor(roles=["member"]))


# --------------------------------------------------------------------------- #
# list
# --------------------------------------------------------------------------- #
def _row(**over: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "id": uuid4(),
        "principal_id": uuid4(),
        "role_id": uuid4(),
        "gremium_id": None,
        "delegated_by": "deleg",
        "granted_by": "deleg",
        "valid_from": None,
        "valid_until": FUTURE,
        "delegate_voting": False,
    }
    base.update(over)
    return SimpleNamespace(**base)


async def test_list_own_returns_mapped() -> None:
    db = fake_session(result(_row(), _row(valid_until=NOW - timedelta(days=1))))
    out = await DelegationService(db, _settings()).list(_actor())
    assert len(out) == 2
    assert out[0].active is True
    assert out[1].active is False  # abgelaufenes Fenster


async def test_list_admin_sees_all() -> None:
    db = fake_session(result(_row(delegated_by="someone-else")))
    out = await DelegationService(db, _settings()).list(
        _actor(perms={"admin.roles"})
    )
    assert len(out) == 1


# --------------------------------------------------------------------------- #
# revoke
# --------------------------------------------------------------------------- #
async def test_revoke_deletes_and_audits() -> None:
    row = SimpleNamespace(id=uuid4(), delegated_by="deleg")
    db = fake_session(result(row), result(), result())  # row + audit lock/prev
    await DelegationService(db, _settings()).revoke(row.id, _actor())
    assert db.deleted == [row]
    assert db.committed == 1
    assert any(type(a).__name__ == "AuditEntry" for a in db.added)


async def test_revoke_not_found_is_404() -> None:
    db = fake_session(result())
    with pytest.raises(NotFoundError):
        await DelegationService(db, _settings()).revoke(uuid4(), _actor())


async def test_revoke_non_delegation_row_is_404() -> None:
    # role_assignment ohne delegated_by ist eine Admin-Zuweisung, keine Delegation.
    db = fake_session(result(SimpleNamespace(id=uuid4(), delegated_by=None)))
    with pytest.raises(NotFoundError):
        await DelegationService(db, _settings()).revoke(uuid4(), _actor())


async def test_revoke_foreign_without_admin_is_403() -> None:
    db = fake_session(result(SimpleNamespace(id=uuid4(), delegated_by="other")))
    with pytest.raises(ForbiddenError):
        await DelegationService(db, _settings()).revoke(uuid4(), _actor(sub="deleg"))


async def test_revoke_foreign_with_admin_ok() -> None:
    row = SimpleNamespace(id=uuid4(), delegated_by="other")
    db = fake_session(result(row), result(), result())
    await DelegationService(db, _settings()).revoke(
        row.id, _actor(sub="deleg", perms={"admin.roles"})
    )
    assert db.deleted == [row]


def test_module_exposes_helper() -> None:
    # Schutz gegen versehentliches Umbenennen des Voting-Hooks.
    assert hasattr(delegations_service, "has_active_voting_delegation")
