"""Flow variant B in the extras dispatcher.

* `addToNextSession` without `gremiumId` takes the snapshot `vote_gremium_id` (R3).
* `assignBudgetFromApplicantGremium` assigns the single node that a Gremium of the
  applicant decides on (R6): one, zero and many matches.
* `assignBudgetFromMap` maps a form-field value to a cost center (R7).
* No cost-center action changes the cost center during a vote whose Gremium comes
  from the cost center.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.modules.flow import extras_dispatcher as extras_mod
from app.modules.flow.dispatch import DispatchedAction
from app.modules.flow.extras_dispatcher import FlowExtrasActionDispatcher


class _Result:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def all(self) -> list[Any]:
        return list(self._items)


class _Session:
    """`scalar` and `scalars` read FIFO queues; `get` reads an id store."""

    def __init__(
        self, *, scalars: list[Any] | None = None, scalar_list: list[list[Any]] | None = None,
        store: dict[UUID, Any] | None = None,
    ) -> None:
        self._scalar = list(scalars or [])
        self._scalars = list(scalar_list or [])
        self.store = store or {}
        self.committed = 0

    async def scalar(self, _stmt: Any) -> Any:
        return self._scalar.pop(0) if self._scalar else None

    async def scalars(self, _stmt: Any) -> _Result:
        return _Result(self._scalars.pop(0) if self._scalars else [])

    async def get(self, _model: Any, ident: UUID) -> Any:
        return self.store.get(ident)

    async def commit(self) -> None:
        self.committed += 1


def _maker(session: _Session) -> Any:
    class _CM:
        async def __aenter__(self) -> _Session:
            return session

        async def __aexit__(self, *_a: Any) -> bool:
            return False

    return lambda: _CM()


def _action(action_type: str, app_id: UUID, **params: Any) -> DispatchedAction:
    return DispatchedAction(
        type=action_type, application_id=app_id, transition_id=uuid4(),
        status_event_id=uuid4(), idempotency_key=f"k:{action_type}", params=params,
    )


def _app(**kw: Any) -> Any:
    base = {
        "id": uuid4(), "created_by": "sub-1", "budget_id": None, "fiscal_year_id": None,
        "current_state_id": None, "data": {},
    }
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture
def audit(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def _fake(_session: Any, **kwargs: Any) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(extras_mod, "audit_record", _fake)
    return calls


@pytest.fixture
def gremien(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    box: list[str] = []

    async def _committees(_session: Any, _sub: str | None) -> frozenset[str]:
        return frozenset(box)

    monkeypatch.setattr(extras_mod, "committee_ids_for_sub", _committees)
    return box


# --- R3 ------------------------------------------------------------------------------


async def test_add_to_next_session_falls_back_to_the_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[UUID, UUID]] = []

    class _Agenda:
        def __init__(self, _s: Any) -> None: ...

        async def add(self, meeting_id: UUID, *, application_id: UUID) -> None:
            calls.append((meeting_id, application_id))

    monkeypatch.setattr(extras_mod, "AgendaService", _Agenda)
    meeting = SimpleNamespace(id=uuid4())
    app_id = uuid4()
    # scalar: the snapshot, then the next meeting.
    session = _Session(scalars=[uuid4(), meeting])
    await FlowExtrasActionDispatcher(_maker(session)).dispatch(
        [_action("addToNextSession", app_id)]
    )
    assert calls == [(meeting.id, app_id)]


async def test_add_to_next_session_without_snapshot_skips() -> None:
    session = _Session(scalars=[None])
    await FlowExtrasActionDispatcher(_maker(session)).dispatch(
        [_action("addToNextSession", uuid4())]
    )
    assert session._scalar == []  # noqa: SLF001 - no meeting lookup followed


async def test_add_to_next_session_empty_gremium_id_skips() -> None:
    session = _Session(scalars=[SimpleNamespace(id=uuid4())])
    await FlowExtrasActionDispatcher(_maker(session)).dispatch(
        [_action("addToNextSession", uuid4(), gremiumId="")]
    )
    assert len(session._scalar) == 1  # noqa: SLF001 - the meeting was never looked up


# --- R6 ------------------------------------------------------------------------------


async def test_applicant_gremium_one_match_assigns(
    audit: list[dict[str, Any]], gremien: list[str]
) -> None:
    gremien.append(str(uuid4()))
    node = SimpleNamespace(id=uuid4(), parent_id=None)
    app = _app()
    session = _Session(store={app.id: app, node.id: node}, scalar_list=[[node.id], []])
    await FlowExtrasActionDispatcher(_maker(session)).dispatch(
        [_action("assignBudgetFromApplicantGremium", app.id)]
    )
    assert app.budget_id == node.id
    assert session.committed == 1
    assert audit[0]["data"]["source"] == "flow:applicantGremium"


@pytest.mark.parametrize("matches", [0, 2])
async def test_applicant_gremium_zero_or_many_assigns_nothing(
    gremien: list[str], matches: int
) -> None:
    gremien.append(str(uuid4()))
    app = _app()
    session = _Session(store={app.id: app}, scalar_list=[[uuid4() for _ in range(matches)]])
    await FlowExtrasActionDispatcher(_maker(session)).dispatch(
        [_action("assignBudgetFromApplicantGremium", app.id)]
    )
    assert app.budget_id is None
    assert session.committed == 0


async def test_applicant_gremium_within_a_subtree(
    audit: list[dict[str, Any]], gremien: list[str]
) -> None:
    gremien.append(str(uuid4()))
    node = SimpleNamespace(id=uuid4(), parent_id=None)
    app = _app()
    parent = uuid4()
    session = _Session(
        store={app.id: app, node.id: node}, scalars=["VSM-8"], scalar_list=[[node.id], []]
    )
    await FlowExtrasActionDispatcher(_maker(session)).dispatch(
        [_action("assignBudgetFromApplicantGremium", app.id, parentId=str(parent))]
    )
    assert app.budget_id == node.id


@pytest.mark.parametrize("parent", ["not-a-uuid", "missing"])
async def test_applicant_gremium_unknown_parent_skips(gremien: list[str], parent: str) -> None:
    gremien.append(str(uuid4()))
    app = _app()
    ref = str(uuid4()) if parent == "missing" else parent
    session = _Session(store={app.id: app}, scalars=[None])
    await FlowExtrasActionDispatcher(_maker(session)).dispatch(
        [_action("assignBudgetFromApplicantGremium", app.id, parentId=ref)]
    )
    assert app.budget_id is None


async def test_applicant_gremium_without_gremien_or_app(gremien: list[str]) -> None:
    app = _app()
    session = _Session(store={app.id: app})
    await FlowExtrasActionDispatcher(_maker(session)).dispatch(
        [
            _action("assignBudgetFromApplicantGremium", app.id),
            _action("assignBudgetFromApplicantGremium", uuid4()),
        ]
    )
    assert app.budget_id is None


# --- R7 ------------------------------------------------------------------------------


async def test_map_assigns_the_mapped_node(audit: list[dict[str, Any]]) -> None:
    node = SimpleNamespace(id=uuid4(), parent_id=None)
    app = _app(data={"we": "Reutlingen"})
    session = _Session(store={app.id: app, node.id: node})
    await FlowExtrasActionDispatcher(_maker(session)).dispatch(
        [_action("assignBudgetFromMap", app.id, field="we", map={"Reutlingen": str(node.id)})]
    )
    assert app.budget_id == node.id
    assert audit[0]["data"]["source"] == "flow:map"


@pytest.mark.parametrize("value", [None, "Tübingen", ["Reutlingen"]])
async def test_map_without_a_match_assigns_nothing(value: object) -> None:
    app = _app(data={"we": value} if value is not None else {})
    session = _Session(store={app.id: app})
    await FlowExtrasActionDispatcher(_maker(session)).dispatch(
        [_action("assignBudgetFromMap", app.id, field="we", map={"Reutlingen": str(uuid4())})]
    )
    assert app.budget_id is None
    assert session.committed == 0


async def test_map_guards() -> None:
    app = _app(data={"we": "x"})
    session = _Session(store={app.id: app})
    await FlowExtrasActionDispatcher(_maker(session)).dispatch(
        [
            _action("assignBudgetFromMap", app.id, map={"x": str(uuid4())}),
            _action("assignBudgetFromMap", app.id, field="we", map="junk"),
            _action("assignBudgetFromMap", uuid4(), field="we", map={"x": str(uuid4())}),
            _action("assignBudgetFromMap", app.id, field="we", map={"x": "not-a-uuid"}),
        ]
    )
    assert app.budget_id is None
    assert session.committed == 0


# --- the cost center is locked during a budget vote -----------------------------------


async def test_assign_skipped_in_a_budget_vote_state(audit: list[dict[str, Any]]) -> None:
    state = SimpleNamespace(kind="vote", config={"gremiumSource": "budget"})
    node = SimpleNamespace(id=uuid4(), parent_id=None)
    app = _app(current_state_id=uuid4())
    session = _Session(store={app.id: app, node.id: node, app.current_state_id: state})
    await FlowExtrasActionDispatcher(_maker(session)).dispatch(
        [_action("assignBudget", app.id, budgetId=str(node.id))]
    )
    assert app.budget_id is None
    assert audit == []


async def test_missing_target_node_assigns_nothing(gremien: list[str]) -> None:
    """The match or the mapped node is gone by the time the action runs."""
    gremien.append(str(uuid4()))
    app = _app(data={"we": "x"})
    session = _Session(store={app.id: app}, scalar_list=[[uuid4()]])
    await FlowExtrasActionDispatcher(_maker(session)).dispatch(
        [
            _action("assignBudgetFromApplicantGremium", app.id),
            _action("assignBudgetFromMap", app.id, field="we", map={"x": str(uuid4())}),
        ]
    )
    assert app.budget_id is None
    assert session.committed == 0
