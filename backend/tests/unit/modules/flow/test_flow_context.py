"""Unit tests for the guard-context split (``build_base_context`` / ``with_actor``).

The actor-free base context and the pure actor overlay were extracted from
``build_context`` (#task-recipients). This suite covers every branch of the
extracted functions plus the recomposed ``build_context`` semantics; the DB
helpers (``_committees_for_sub``/``_field_types``/``_budget_fits``) keep their
own branch coverage in ``test_deadlines_flow_cov``.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest

from app.modules.auth.principal import Principal
from app.modules.flow import context as flow_context

# Original helper-Bindings (unabhängig vom autouse-Monkeypatch, der die Modul-Attribute
# ersetzt) — für die direkten Coverage-Tests ihrer realen Rümpfe.
from app.modules.flow.context import (
    _application_type_key,
    _has_attachment,
    build_base_context,
    build_context,
    with_actor,
)
from app.shared.guards import GuardContext
from tests._support.flow_fakes import FakeSession, fake_session


def _app(**over: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "data": {},
        "created_by": None,
        "budget_id": None,
        "fiscal_year_id": None,
        "amount": Decimal("5"),
        "form_version_id": uuid4(),
        "type_id": uuid4(),
    }
    base.update(over)
    return SimpleNamespace(**base)


def _principal(**over: object) -> Principal:
    base: dict[str, object] = {"sub": "actor-1", "roles": ["chair"], "permissions": set()}
    base.update(over)
    return Principal(**base)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _pure_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    """DB-free helpers: committees keyed by sub, static field types, no budget fit."""

    async def _cs(_session: object, sub: str | None) -> frozenset[str]:
        return frozenset({f"g-{sub}"}) if sub else frozenset()

    async def _ft(_session: object, _app: object) -> dict[str, str]:
        return {"amount": "currency"}

    async def _bf(_session: object, _app: object) -> bool:
        return False

    async def _atk(_session: object, _app: object) -> str | None:
        return "qsm"

    async def _ha(_session: object, _app: object) -> bool:
        return False

    monkeypatch.setattr(flow_context, "_committees_for_sub", _cs)
    monkeypatch.setattr(flow_context, "_field_types", _ft)
    monkeypatch.setattr(flow_context, "_budget_fits", _bf)
    monkeypatch.setattr(flow_context, "_application_type_key", _atk)
    monkeypatch.setattr(flow_context, "_has_attachment", _ha)


# --------------------------------------------------------------------------- #
# with_actor (pure)
# --------------------------------------------------------------------------- #
def test_with_actor_overlays_on_manual_context() -> None:
    base = GuardContext(
        manual=True, deadline_passed=True, applicant_roles=frozenset({"member"})
    )
    ctx = with_actor(
        base,
        roles=frozenset({"chair"}),
        committees=frozenset({"g-1"}),
        is_applicant=True,
    )
    assert ctx.roles == frozenset({"chair"})
    assert ctx.actor_committees == frozenset({"g-1"})
    assert ctx.actor_is_applicant is True
    # Actor-free facts stay untouched.
    assert ctx.deadline_passed is True
    assert ctx.applicant_roles == frozenset({"member"})
    # Pure overlay: the base context itself is unchanged (frozen + replace).
    assert base.roles == frozenset()
    assert base.actor_is_applicant is False


def test_with_actor_strips_on_automatic_context() -> None:
    base = GuardContext(manual=False)
    ctx = with_actor(
        base,
        roles=frozenset({"chair"}),
        committees=frozenset({"g-1"}),
        is_applicant=True,
    )
    assert ctx.roles == frozenset()
    assert ctx.actor_committees == frozenset()
    assert ctx.actor_is_applicant is False


def test_with_actor_manual_not_applicant() -> None:
    ctx = with_actor(
        GuardContext(manual=True),
        roles=frozenset(),
        committees=frozenset(),
        is_applicant=False,
    )
    assert ctx.actor_is_applicant is False


# --------------------------------------------------------------------------- #
# build_base_context (actor-free I/O)
# --------------------------------------------------------------------------- #
async def test_base_context_collects_actor_free_facts() -> None:
    app = _app(
        data={"_applicantRoles": ["member"], "feld": 1},
        created_by="creator",
        budget_id=uuid4(),
    )
    ctx = await build_base_context(fake_session(), cast("Any", app), manual=True)
    assert ctx.manual is True
    assert ctx.deadline_passed is False
    # Actor fields stay at their empty defaults.
    assert ctx.roles == frozenset()
    assert ctx.actor_committees == frozenset()
    assert ctx.actor_is_applicant is False
    assert ctx.applicant_roles == frozenset({"member"})
    assert ctx.applicant_committees == frozenset({"g-creator"})
    assert ctx.budget_id == str(app.budget_id)
    assert ctx.budget_fits is False
    assert ctx.field_values["feld"] == 1
    assert ctx.field_values["amount"] == app.amount
    assert ctx.field_types == {"amount": "currency"}
    assert ctx.application_type_key == "qsm"
    assert ctx.has_attachment is False


async def test_application_type_key_helper_reads_scalar() -> None:
    session = FakeSession()
    session.scalar_results = ["qsm"]
    assert await _application_type_key(cast("Any", session), cast("Any", _app())) == "qsm"


async def test_has_attachment_helper_reads_scalar() -> None:
    present = FakeSession()
    present.scalar_results = [True]
    assert await _has_attachment(cast("Any", present), cast("Any", _app(id=uuid4()))) is True
    absent = FakeSession()
    absent.scalar_results = [None]
    assert await _has_attachment(cast("Any", absent), cast("Any", _app(id=uuid4()))) is False


async def test_base_context_data_not_dict() -> None:
    app = _app(data=None)
    ctx = await build_base_context(fake_session(), cast("Any", app), manual=True)
    assert ctx.applicant_roles == frozenset()
    assert ctx.field_values == {"amount": app.amount}
    assert ctx.budget_id is None


async def test_base_context_applicant_roles_not_list() -> None:
    app = _app(data={"_applicantRoles": "not-a-list"})
    ctx = await build_base_context(fake_session(), cast("Any", app), manual=True)
    assert ctx.applicant_roles == frozenset()


async def test_base_context_flags_propagate() -> None:
    ctx = await build_base_context(
        fake_session(), cast("Any", _app()), manual=False, deadline_passed=True
    )
    assert ctx.manual is False
    assert ctx.deadline_passed is True


# --------------------------------------------------------------------------- #
# build_context — recomposition (base + actor overlay, unchanged semantics)
# --------------------------------------------------------------------------- #
async def test_build_context_manual_creator_is_applicant() -> None:
    app = _app(created_by="actor-1")
    ctx = await build_context(fake_session(), cast("Any", app), _principal(), manual=True)
    assert ctx.roles == frozenset({"chair"})
    assert ctx.actor_committees == frozenset({"g-actor-1"})
    assert ctx.actor_is_applicant is True


async def test_build_context_manual_as_applicant_magic_link() -> None:
    app = _app(created_by="someone-else")
    ctx = await build_context(
        fake_session(), cast("Any", app), _principal(), manual=True, as_applicant=True
    )
    assert ctx.actor_is_applicant is True


async def test_build_context_manual_foreign_actor_not_applicant() -> None:
    app = _app(created_by="someone-else")
    ctx = await build_context(fake_session(), cast("Any", app), _principal(), manual=True)
    assert ctx.actor_is_applicant is False


async def test_build_context_created_by_none_not_applicant() -> None:
    app = _app(created_by=None)
    ctx = await build_context(fake_session(), cast("Any", app), _principal(), manual=True)
    assert ctx.actor_is_applicant is False


async def test_build_context_automatic_strips_actor_signals() -> None:
    app = _app(created_by="actor-1")
    ctx = await build_context(
        fake_session(), cast("Any", app), _principal(), manual=False, as_applicant=True
    )
    assert ctx.manual is False
    assert ctx.roles == frozenset()
    assert ctx.actor_committees == frozenset()
    assert ctx.actor_is_applicant is False
    # Applicant facts from the base context survive the strip.
    assert ctx.applicant_committees == frozenset({"g-actor-1"})
