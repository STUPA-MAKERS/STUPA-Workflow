"""TDD: FlowExtrasActionDispatcher (#28) — addToNextSession + assignBudget.

Reine Branch-Abdeckung ohne DB: ein In-Memory-Session-Fake (``get``/``scalar``/
``scalars``/``commit``) + ein Sessionmaker-Wrapper. AgendaService wird gepatcht.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.modules.flow import extras_dispatcher as extras_mod
from app.modules.flow.dispatch import DispatchedAction
from app.modules.flow.extras_dispatcher import FlowExtrasActionDispatcher
from app.shared.errors import ConflictError, NotFoundError


class _Result:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def all(self) -> list[Any]:
        return list(self._items)


class _Session:
    """``AsyncSession``-Fake: ``get`` per Id-Store, ``scalar``/``scalars`` fix."""

    def __init__(
        self,
        *,
        meeting: Any = None,
        store: dict[UUID, Any] | None = None,
        active_fy: tuple[UUID, ...] = (),
        raise_on_get: bool = False,
    ) -> None:
        self.meeting = meeting
        self.store = store or {}
        self.active_fy = list(active_fy)
        self.raise_on_get = raise_on_get
        self.committed = 0

    async def scalar(self, _stmt: Any) -> Any:
        return self.meeting

    async def get(self, _model: Any, ident: UUID) -> Any:
        if self.raise_on_get:
            raise RuntimeError("boom")
        return self.store.get(ident)

    async def scalars(self, _stmt: Any) -> _Result:
        return _Result(self.active_fy)

    async def commit(self) -> None:
        self.committed += 1


def _stub_audit(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Patch the audit hook to record (kein echtes ``AuditService`` nötig)."""
    calls: list[dict[str, Any]] = []

    async def _fake(_session: Any, **kwargs: Any) -> Any:
        calls.append(kwargs)
        return None

    monkeypatch.setattr(extras_mod, "audit_record", _fake)
    return calls


def _maker(session: _Session) -> Any:
    class _CM:
        async def __aenter__(self) -> _Session:
            return session

        async def __aexit__(self, *_a: Any) -> bool:
            return False

    return lambda: _CM()


def _action(
    action_type: str, *, application_id: UUID | None = None, **params: Any
) -> DispatchedAction:
    return DispatchedAction(
        type=action_type,
        application_id=application_id or uuid4(),
        transition_id=uuid4(),
        status_event_id=uuid4(),
        idempotency_key="app:evt:0:" + action_type,
        params=params,
    )


# --------------------------------------------------------------- dispatch routing #
async def test_dispatch_ignores_other_action_types() -> None:
    session = _Session()
    await FlowExtrasActionDispatcher(_maker(session)).dispatch(
        [_action("notify", group="gremium")]
    )
    assert session.committed == 0


async def test_dispatch_swallows_action_errors() -> None:
    # session.get wirft → dispatch fängt + loggt, propagiert NICHT (flows §9.3).
    session = _Session(raise_on_get=True)
    await FlowExtrasActionDispatcher(_maker(session)).dispatch(
        [_action("assignBudget", budgetId=str(uuid4()), application_id=uuid4())]
    )  # kein Raise
    assert session.committed == 0


# ----------------------------------------------------------- addToNextSession #
async def test_add_to_next_session_without_gremium_id_skipped() -> None:
    session = _Session()
    await FlowExtrasActionDispatcher(_maker(session)).dispatch([_action("addToNextSession")])
    assert session.committed == 0


async def test_add_to_next_session_invalid_gremium_id_skipped() -> None:
    session = _Session()
    await FlowExtrasActionDispatcher(_maker(session)).dispatch(
        [_action("addToNextSession", gremiumId="not-a-uuid")]
    )
    assert session.committed == 0


async def test_add_to_next_session_no_upcoming_meeting_skipped() -> None:
    session = _Session(meeting=None)
    await FlowExtrasActionDispatcher(_maker(session)).dispatch(
        [_action("addToNextSession", gremiumId=str(uuid4()))]
    )
    assert session.committed == 0


async def test_add_to_next_session_adds_to_agenda(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[UUID, UUID]] = []

    class _FakeAgenda:
        def __init__(self, _session: Any) -> None: ...

        async def add(self, meeting_id: UUID, *, application_id: UUID) -> None:
            calls.append((meeting_id, application_id))

    monkeypatch.setattr(extras_mod, "AgendaService", _FakeAgenda)
    meeting = SimpleNamespace(id=uuid4())
    action = _action("addToNextSession", gremiumId=str(uuid4()))
    await FlowExtrasActionDispatcher(_maker(_Session(meeting=meeting))).dispatch([action])
    assert calls == [(meeting.id, action.application_id)]


async def test_add_to_next_session_agenda_conflict_is_logged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeAgenda:
        def __init__(self, _session: Any) -> None: ...

        async def add(self, _meeting_id: UUID, *, application_id: UUID) -> None:
            raise ConflictError("already on agenda")

    monkeypatch.setattr(extras_mod, "AgendaService", _FakeAgenda)
    session = _Session(meeting=SimpleNamespace(id=uuid4()))
    await FlowExtrasActionDispatcher(_maker(session)).dispatch(
        [_action("addToNextSession", gremiumId=str(uuid4()))]
    )  # NotFound/Conflict gefangen → kein Raise


async def test_add_to_next_session_agenda_not_found_is_logged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeAgenda:
        def __init__(self, _session: Any) -> None: ...

        async def add(self, _meeting_id: UUID, *, application_id: UUID) -> None:
            raise NotFoundError("meeting gone")

    monkeypatch.setattr(extras_mod, "AgendaService", _FakeAgenda)
    session = _Session(meeting=SimpleNamespace(id=uuid4()))
    await FlowExtrasActionDispatcher(_maker(session)).dispatch(
        [_action("addToNextSession", gremiumId=str(uuid4()))]
    )


# --------------------------------------------------------------- assignBudget #
async def test_assign_budget_without_budget_id_skipped() -> None:
    session = _Session()
    await FlowExtrasActionDispatcher(_maker(session)).dispatch([_action("assignBudget")])
    assert session.committed == 0


async def test_assign_budget_invalid_budget_id_skipped() -> None:
    session = _Session()
    await FlowExtrasActionDispatcher(_maker(session)).dispatch(
        [_action("assignBudget", budgetId="nope")]
    )
    assert session.committed == 0


async def test_assign_budget_missing_app_or_node_skipped() -> None:
    # Store leer → get liefert None → übersprungen, kein Commit.
    session = _Session(store={})
    await FlowExtrasActionDispatcher(_maker(session)).dispatch(
        [_action("assignBudget", budgetId=str(uuid4()), application_id=uuid4())]
    )
    assert session.committed == 0


async def test_assign_budget_sets_single_active_fiscal_year(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_audit(monkeypatch)
    app_id, node_id, fy_id = uuid4(), uuid4(), uuid4()
    app = SimpleNamespace(id=app_id, budget_id=None, fiscal_year_id=None)
    node = SimpleNamespace(id=node_id, parent_id=None)  # Top-Level
    session = _Session(store={app_id: app, node_id: node}, active_fy=(fy_id,))
    await FlowExtrasActionDispatcher(_maker(session)).dispatch(
        [_action("assignBudget", budgetId=str(node_id), application_id=app_id)]
    )
    assert app.budget_id == node_id
    assert app.fiscal_year_id == fy_id
    assert session.committed == 1


async def test_assign_budget_ambiguous_fiscal_year_left_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_audit(monkeypatch)
    app_id, node_id = uuid4(), uuid4()
    app = SimpleNamespace(id=app_id, budget_id=None, fiscal_year_id=None)
    node = SimpleNamespace(id=node_id, parent_id=None)
    session = _Session(store={app_id: app, node_id: node}, active_fy=(uuid4(), uuid4()))
    await FlowExtrasActionDispatcher(_maker(session)).dispatch(
        [_action("assignBudget", budgetId=str(node_id), application_id=app_id)]
    )
    assert app.budget_id == node_id
    assert app.fiscal_year_id is None  # mehrdeutig → offen gelassen
    assert session.committed == 1


async def test_assign_budget_writes_audit_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Geld-Mutation per Flow-Action MUSS einen BUDGET_ASSIGN-Audit-Eintrag schreiben
    (Hausregel: alle Budget-Mutationen sind im append-only Audit-Trail belegt)."""
    from app.modules.audit.actions import AuditAction

    calls = _stub_audit(monkeypatch)
    app_id, node_id, fy_id = uuid4(), uuid4(), uuid4()
    app = SimpleNamespace(id=app_id, budget_id=None, fiscal_year_id=None)
    node = SimpleNamespace(id=node_id, parent_id=None)
    session = _Session(store={app_id: app, node_id: node}, active_fy=(fy_id,))
    await FlowExtrasActionDispatcher(_maker(session)).dispatch(
        [_action("assignBudget", budgetId=str(node_id), application_id=app_id)]
    )
    assert len(calls) == 1
    rec = calls[0]
    assert rec["action"] == AuditAction.BUDGET_ASSIGN
    assert rec["actor"] == extras_mod._FLOW_ACTOR
    assert rec["target_type"] == "application"
    assert rec["target_id"] == str(app_id)
    assert rec["data"]["budgetId"] == str(node_id)
    assert rec["data"]["fiscalYearId"] == str(fy_id)
    assert rec["data"]["source"] == "flow"
    assert session.committed == 1


# ------------------------------------------------------------------ _top_level #
async def test_top_level_walks_parent_chain() -> None:
    root = SimpleNamespace(id=uuid4(), parent_id=None)
    mid = SimpleNamespace(id=uuid4(), parent_id=root.id)
    leaf = SimpleNamespace(id=uuid4(), parent_id=mid.id)
    session = _Session(store={root.id: root, mid.id: mid, leaf.id: leaf})
    top = await FlowExtrasActionDispatcher._top_level(session, leaf)  # pyright: ignore[reportArgumentType]
    assert top is root


async def test_top_level_breaks_on_missing_parent() -> None:
    node = SimpleNamespace(id=uuid4(), parent_id=uuid4())  # Eltern fehlen
    session = _Session(store={node.id: node})
    top = await FlowExtrasActionDispatcher._top_level(session, node)  # pyright: ignore[reportArgumentType]
    assert top is node


async def test_top_level_stops_on_cycle() -> None:
    a = SimpleNamespace(id=uuid4())
    b = SimpleNamespace(id=uuid4())
    a.parent_id = b.id
    b.parent_id = a.id
    session = _Session(store={a.id: a, b.id: b})
    top = await FlowExtrasActionDispatcher._top_level(session, a)  # pyright: ignore[reportArgumentType]
    assert top is b  # a → b → (a bereits gesehen) Stop


def test_build_flow_extras_dispatcher_needs_no_pool() -> None:
    disp = extras_mod.build_flow_extras_dispatcher(None)
    assert isinstance(disp, FlowExtrasActionDispatcher)
