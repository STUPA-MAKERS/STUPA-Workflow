"""Bulk transitions without a database (specs 001700, 001701, 001703).

§ 001701 the options are the targets that every selected Antrag reaches, an Antrag that
the person cannot read leaves no option, an agenda transition is never offered, and an
approving target lists the requested amounts. § 001703 each Antrag runs on its own: an
error rolls back that Antrag and names the code, the others go on.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from app.modules.auth.principal import Principal
from app.modules.flow import bulk
from app.shared.errors import ConflictError

_PRINCIPAL = Principal(sub="mgr", roles=["member"], permissions={"application.manage"})


def _t(to: UUID, *, approves: bool = False, agenda: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        to_state_id=to,
        label={"de": "Ziel"},
        color=None,
        allows_decision=approves,
        adds_to_agenda=agenda,
    )


class _Session:
    def __init__(self, apps: dict[UUID, Any]) -> None:
        self.apps = apps
        self.rollbacks = 0

    async def get(self, _model: object, key: UUID) -> Any:
        return self.apps.get(key)

    async def rollback(self) -> None:
        self.rollbacks += 1


class _Service:
    def __init__(
        self,
        offered: dict[UUID, list[SimpleNamespace]],
        apps: dict[UUID, Any] | None = None,
        failing: set[UUID] | None = None,
    ) -> None:
        self.session = _Session(apps or {})
        self.offered = offered
        self.failing = failing or set()
        self.fired: list[tuple[UUID, UUID, Any]] = []

    async def available_transitions(
        self, application_id: UUID, _principal: Principal, *, allow_unconfirmed: bool
    ) -> list[SimpleNamespace]:
        assert allow_unconfirmed is False
        return self.offered[application_id]

    async def fire(
        self, application_id: UUID, transition_id: UUID, _principal: Principal, **kw: Any
    ) -> None:
        if application_id in self.failing:
            raise ConflictError("Guard says no.", code="guard_failed")
        self.fired.append((application_id, transition_id, kw["decision"]))


@pytest.fixture
def unreadable(monkeypatch: pytest.MonkeyPatch) -> set[UUID]:
    """Patch the read check: an id in the set is not readable."""
    box: set[UUID] = set()

    async def _read(_db: object, application_id: UUID, _p: object, _a: object) -> None:
        if application_id in box:
            raise ConflictError("Not readable.", code="not_readable")

    monkeypatch.setattr(bulk, "resolve_app_read", _read)
    return box


def _app(app_id: UUID, title: object, amount: str | None) -> SimpleNamespace:
    return SimpleNamespace(
        id=app_id,
        data={"title": title} if title is not None else None,
        amount=Decimal(amount) if amount is not None else None,
    )


async def test_options_are_the_common_targets_with_the_amounts(unreadable: set[UUID]) -> None:
    a, b, c = uuid4(), uuid4(), uuid4()
    ok, back, other, agenda = uuid4(), uuid4(), uuid4(), uuid4()
    service = _Service(
        offered={
            a: [_t(ok, approves=True), _t(back), _t(agenda, agenda=True), _t(other)],
            b: [_t(ok, approves=True), _t(back), _t(agenda, agenda=True)],
            c: [_t(ok, approves=True), _t(back)],
        },
        apps={a: _app(a, "  Sommerfest ", "1250.00"), b: _app(b, "   ", None)},
    )
    out = await bulk.bulk_options(cast(Any, service), [a, b, c, a], _PRINCIPAL)
    by_target = {o.to_state_id: o for o in out}
    assert set(by_target) == {ok, back}
    approve = by_target[ok]
    assert approve.approves is True
    assert [(x.application_id, x.title, x.amount) for x in approve.amounts] == [
        (a, "Sommerfest", Decimal("1250.00")),
        (b, None, None),
    ]
    assert by_target[back].amounts == ()


async def test_options_without_an_approving_target_load_no_amounts(
    unreadable: set[UUID],
) -> None:
    a = uuid4()
    back = uuid4()
    service = _Service(offered={a: [_t(back)]}, apps={a: _app(a, 5, "1.00")})
    out = await bulk.bulk_options(cast(Any, service), [a], _PRINCIPAL)
    assert [(o.to_state_id, o.approves, o.amounts) for o in out] == [(back, False, ())]


async def test_an_unreadable_antrag_leaves_no_option(unreadable: set[UUID]) -> None:
    a, b = uuid4(), uuid4()
    unreadable.add(b)
    service = _Service(offered={a: [_t(uuid4())], b: [_t(uuid4())]})
    assert await bulk.bulk_options(cast(Any, service), [a, b], _PRINCIPAL) == []


async def test_fire_runs_each_antrag_on_its_own(unreadable: set[UUID]) -> None:
    a, b, c, d, gone = uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    ok, back = uuid4(), uuid4()
    unreadable.add(d)
    approve = {i: _t(ok, approves=True) for i in (a, b, gone)}
    service = _Service(
        offered={a: [approve[a]], b: [approve[b]], c: [_t(back)], d: [], gone: [approve[gone]]},
        apps={a: _app(a, "A", "100.00"), b: _app(b, "B", "50.00")},
        failing={b},
    )
    results = await bulk.bulk_fire(
        cast(Any, service), [a, b, c, d, gone, a], ok, _PRINCIPAL, note="Sammel"
    )
    assert [(r.application_id, r.ok, r.code) for r in results] == [
        (a, True, None),
        (b, False, "guard_failed"),
        (c, False, bulk.BULK_NOT_AVAILABLE),
        (d, False, "not_readable"),
        (gone, True, None),
    ]
    assert service.session.rollbacks == 3
    fired = {app_id: (tid, decision) for app_id, tid, decision in service.fired}
    assert fired[a][0] == approve[a].id
    assert fired[a][1].approved_amount == Decimal("100.00")
    assert fired[gone][1] is None


async def test_fire_into_a_plain_target_sends_no_decision(unreadable: set[UUID]) -> None:
    a = uuid4()
    back = _t(uuid4())
    service = _Service(offered={a: [back]}, apps={a: _app(a, "A", "10.00")})
    results = await bulk.bulk_fire(cast(Any, service), [a], back.to_state_id, _PRINCIPAL)
    assert [r.ok for r in results] == [True]
    assert service.fired == [(a, back.id, None)]
