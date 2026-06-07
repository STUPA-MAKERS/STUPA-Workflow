"""TDD: DelegationService (T-45) — Config-Gate, Fenster, Sicherheitskern, Audit.

Jede Service-Verzweigung wird über einen Ergebnis-Queue-Fake (``flow_fakes``)
deterministisch getroffen — keine echte DB. Enthält die Eskalations-**Negativtests**
aus security-review #95: zeitliche Klammer, Re-Delegation/Kette, Gremium-Scope,
Doppel-Stimmrecht.

Query-Reihenfolge in ``create`` (für die Fake-Queue): delegate → role → me →
direct-holdings → audit(lock,prev).
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
    voting_delegation_check,
)
from app.settings import load_settings
from app.shared.errors import ForbiddenError, NotFoundError, ValidationProblem
from tests.flow_fakes import fake_session, result

NOW = datetime(2026, 6, 6, 12, 0, tzinfo=UTC)
FUTURE = datetime(2099, 1, 1, tzinfo=UTC)


def _settings(*, voting: bool = False) -> Any:
    return load_settings(delegation_voting_enabled=voting)


def _actor(sub: str = "deleg", perms: set[str] | None = None) -> Principal:
    return Principal(sub=sub, roles=["member"], permissions=perms or set())


def _payload(**over: Any) -> DelegationCreate:
    base: dict[str, Any] = {
        "principal_id": uuid4(),
        "role_id": uuid4(),
        "valid_until": FUTURE,
        "delegate_voting": False,
    }
    base.update(over)
    return DelegationCreate(**base)


def _delegate(sub: str = "other") -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), sub=sub)


def _role() -> SimpleNamespace:
    return SimpleNamespace(key="member")


def _me() -> SimpleNamespace:
    return SimpleNamespace(id=uuid4())


def _holding(
    gremium_id: Any = None, valid_from: datetime | None = None, valid_until: datetime | None = None
) -> tuple[Any, datetime | None, datetime | None]:
    """Direct-holding-Zeile wie aus ``select(gremium_id, valid_from, valid_until)``."""
    return (gremium_id, valid_from, valid_until)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def test_to_utc_normalizes() -> None:
    assert _to_utc(None) is None
    naive = datetime(2026, 6, 6, 12, 0)
    assert _to_utc(naive) == datetime(2026, 6, 6, 12, 0, tzinfo=UTC)
    aware = datetime(2026, 6, 6, 14, 0, tzinfo=UTC)
    assert _to_utc(aware) == aware


async def test_voting_delegation_check_classifies_both_sides() -> None:
    # delegator gave voting away → blocked
    db = fake_session(result(("me", True)))
    assert await voting_delegation_check(db, "me", None, NOW) == (True, False)
    # recipient via NON-voting delegation → blocked
    db = fake_session(result(("other", False)))
    assert await voting_delegation_check(db, "me", None, NOW) == (True, False)
    # recipient via voting delegation → exercised
    db = fake_session(result(("other", True)))
    assert await voting_delegation_check(db, "me", None, NOW) == (False, True)
    # nothing → normal
    db = fake_session(result())
    assert await voting_delegation_check(db, "me", None, NOW) == (False, False)


async def test_voting_delegation_check_scope_branches() -> None:
    # _scope_clause: None, gültige UUID, Nicht-UUID — alle Branches.
    db = fake_session(result(), result(), result())
    assert await voting_delegation_check(db, "me", None, NOW) == (False, False)
    assert await voting_delegation_check(db, "me", str(uuid4()), NOW) == (False, False)
    assert await voting_delegation_check(db, "me", "not-a-uuid", NOW) == (False, False)


# --------------------------------------------------------------------------- #
# create — happy + audit
# --------------------------------------------------------------------------- #
async def test_create_persists_and_audits() -> None:
    db = fake_session(
        result(_delegate()),  # delegate exists
        result(_role()),  # role exists
        result(_me()),  # delegator principal
        result(_holding()),  # direct, global, unbounded holding
        result(),  # audit advisory lock
        result(),  # audit prev-hash
    )
    out = await DelegationService(db, _settings()).create(_payload(), _actor())
    assert out.delegated_by == "deleg"
    assert out.granted_by == "deleg"
    assert out.active is True
    assert out.valid_until == FUTURE  # unbefristetes Recht → kein Clamp
    assert db.committed == 1
    persisted = [a for a in db.added if isinstance(a, RoleAssignment)]
    assert len(persisted) == 1 and persisted[0].delegated_by == "deleg"
    assert any(type(a).__name__ == "AuditEntry" for a in db.added)


async def test_create_voting_enabled_ok() -> None:
    db = fake_session(
        result(_delegate()), result(_role()), result(_me()), result(_holding()),
        result(), result(),
    )
    out = await DelegationService(db, _settings(voting=True)).create(
        _payload(delegate_voting=True), _actor()
    )
    assert out.delegate_voting is True


# --------------------------------------------------------------------------- #
# create — pre-DB guards
# --------------------------------------------------------------------------- #
async def test_create_voting_disabled_is_422() -> None:
    db = fake_session()
    with pytest.raises(ValidationProblem) as ei:
        await DelegationService(db, _settings(voting=False)).create(
            _payload(delegate_voting=True), _actor()
        )
    assert ei.value.status == 422
    assert db.committed == 0


async def test_create_validuntil_before_from_is_422() -> None:
    db = fake_session()
    with pytest.raises(ValidationProblem):
        await DelegationService(db, _settings()).create(
            _payload(valid_from=FUTURE, valid_until=FUTURE - timedelta(days=1)), _actor()
        )


async def test_create_validuntil_in_past_is_422() -> None:
    db = fake_session()
    with pytest.raises(ValidationProblem):
        await DelegationService(db, _settings()).create(
            _payload(valid_until=NOW - timedelta(days=3650)), _actor()
        )


# --------------------------------------------------------------------------- #
# create — lookups
# --------------------------------------------------------------------------- #
async def test_create_unknown_principal_is_404() -> None:
    db = fake_session(result())  # delegate not found
    with pytest.raises(NotFoundError):
        await DelegationService(db, _settings()).create(_payload(), _actor())


async def test_create_self_delegation_is_422() -> None:
    db = fake_session(result(_delegate(sub="deleg")))  # same sub as actor
    with pytest.raises(ValidationProblem):
        await DelegationService(db, _settings()).create(_payload(), _actor(sub="deleg"))


async def test_create_unknown_role_is_404() -> None:
    db = fake_session(result(_delegate()), result())  # role not found
    with pytest.raises(NotFoundError):
        await DelegationService(db, _settings()).create(_payload(), _actor())


async def test_create_delegator_principal_missing_is_403() -> None:
    db = fake_session(result(_delegate()), result(_role()), result())  # me not found
    with pytest.raises(ForbiddenError):
        await DelegationService(db, _settings()).create(_payload(), _actor())


# --------------------------------------------------------------------------- #
# create — ESKALATIONS-NEGATIVTESTS (security-review #95)
# --------------------------------------------------------------------------- #
async def test_create_re_delegation_forbidden_is_403() -> None:
    # #2: keine direkt gehaltene (delegated_by IS NULL) Zeile → nicht delegierbar.
    db = fake_session(result(_delegate()), result(_role()), result(_me()), result())
    with pytest.raises(ForbiddenError, match="directly"):
        await DelegationService(db, _settings()).create(_payload(), _actor())


async def test_create_gremium_scope_exceeds_holdings_is_403() -> None:
    # #4: Recht nur in Gremium G gehalten, Delegation nach H → Scope-Eskalation 403.
    g, h = uuid4(), uuid4()
    db = fake_session(
        result(_delegate()), result(_role()), result(_me()), result(_holding(gremium_id=g))
    )
    with pytest.raises(ForbiddenError, match="scope"):
        await DelegationService(db, _settings()).create(
            _payload(gremium_id=h), _actor()
        )


async def test_create_global_delegation_without_global_holding_is_403() -> None:
    # #4: nur scoped gehalten → globale (gremium_id=None) Delegation unzulässig.
    g = uuid4()
    db = fake_session(
        result(_delegate()), result(_role()), result(_me()), result(_holding(gremium_id=g))
    )
    with pytest.raises(ForbiddenError, match="scope"):
        await DelegationService(db, _settings()).create(
            _payload(gremium_id=None), _actor()
        )


async def test_create_scoped_holding_covers_same_scope_ok() -> None:
    g = uuid4()
    db = fake_session(
        result(_delegate()), result(_role()), result(_me()),
        result(_holding(gremium_id=g)), result(), result(),
    )
    out = await DelegationService(db, _settings()).create(
        _payload(gremium_id=g), _actor()
    )
    assert out.gremium_id == g


async def test_create_clamps_validuntil_to_own_window() -> None:
    # #1: eigenes Recht endet bei T; Wunsch T+ → Delegation wird auf T geklemmt.
    t = NOW + timedelta(days=10)
    db = fake_session(
        result(_delegate()), result(_role()), result(_me()),
        result(_holding(valid_until=t)), result(), result(),
    )
    out = await DelegationService(db, _settings()).create(
        _payload(valid_until=NOW + timedelta(days=365)), _actor()
    )
    assert out.valid_until == t  # geklemmt aufs eigene Fenster


async def test_create_effective_window_elapsed_is_422() -> None:
    # validFrom/validUntil beide in der Vergangenheit (until>from) → nach Klammer 422.
    db = fake_session(
        result(_delegate()), result(_role()), result(_me()), result(_holding())
    )
    with pytest.raises(ValidationProblem, match="elapsed"):
        await DelegationService(db, _settings()).create(
            _payload(
                valid_from=NOW - timedelta(days=10), valid_until=NOW - timedelta(days=5)
            ),
            _actor(),
        )


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
    assert out[1].active is False


async def test_list_admin_sees_all() -> None:
    db = fake_session(result(_row(delegated_by="someone-else")))
    out = await DelegationService(db, _settings()).list(_actor(perms={"admin.roles"}))
    assert len(out) == 1


# --------------------------------------------------------------------------- #
# revoke
# --------------------------------------------------------------------------- #
async def test_revoke_deletes_and_audits() -> None:
    row = SimpleNamespace(id=uuid4(), delegated_by="deleg")
    db = fake_session(result(row), result(), result())
    await DelegationService(db, _settings()).revoke(row.id, _actor())
    assert db.deleted == [row]
    assert db.committed == 1
    assert any(type(a).__name__ == "AuditEntry" for a in db.added)


async def test_revoke_not_found_is_404() -> None:
    db = fake_session(result())
    with pytest.raises(NotFoundError):
        await DelegationService(db, _settings()).revoke(uuid4(), _actor())


async def test_revoke_non_delegation_row_is_404() -> None:
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


def test_module_exposes_voting_hook() -> None:
    assert hasattr(delegations_service, "voting_delegation_check")
