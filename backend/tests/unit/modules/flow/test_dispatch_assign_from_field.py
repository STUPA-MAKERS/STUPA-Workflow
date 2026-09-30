"""F1: the flow action `assignBudgetFromField` really runs.

The validation accepts the action, but the worker filter dropped it before this fix,
so the extras dispatcher never saw it. The action now reaches the dispatcher. A retry
with the same idempotency key changes nothing and writes no second audit entry.
F2: `build_worker_dispatcher` chains the notify, webhook and extras dispatchers.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.modules.flow import extras_dispatcher as extras_mod
from app.modules.flow.dispatch import (
    WORKER_ACTION_TYPES,
    ChainActionDispatcher,
    build_dispatched_actions,
    build_worker_dispatcher,
)
from app.modules.flow.extras_dispatcher import FlowExtrasActionDispatcher
from app.modules.notifications.action_dispatcher import NotificationActionDispatcher
from app.modules.webhooks.action_dispatcher import WebhookActionDispatcher
from app.settings import load_settings


class _Result:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def all(self) -> list[Any]:
        return list(self._items)


class _Session:
    def __init__(self, store: dict[UUID, Any], active_fy: tuple[UUID, ...]) -> None:
        self.store = store
        self.active_fy = list(active_fy)
        self.committed = 0

    async def get(self, _model: Any, ident: UUID) -> Any:
        return self.store.get(ident)

    async def scalars(self, _stmt: Any) -> _Result:
        return _Result(self.active_fy)

    async def commit(self) -> None:
        self.committed += 1


def _maker(session: _Session) -> Any:
    class _CM:
        async def __aenter__(self) -> _Session:
            return session

        async def __aexit__(self, *_a: Any) -> bool:
            return False

    return lambda: _CM()


def test_assign_budget_from_field_is_a_worker_action() -> None:
    assert "assignBudgetFromField" in WORKER_ACTION_TYPES
    app_id, event_id = uuid4(), uuid4()
    dispatched = build_dispatched_actions(
        [{"type": "assignBudgetFromField", "field": "ziel"}],
        application_id=app_id,
        transition_id=uuid4(),
        status_event_id=event_id,
    )
    assert [a.type for a in dispatched] == ["assignBudgetFromField"]
    assert dispatched[0].params == {"field": "ziel"}
    assert dispatched[0].idempotency_key == f"{app_id}:{event_id}:0:assignBudgetFromField"


async def test_assign_from_field_runs_once_per_idempotency_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    async def _audit(_session: Any, **kwargs: Any) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(extras_mod, "audit_record", _audit)
    app_id, node_id, fy_id = uuid4(), uuid4(), uuid4()
    app = SimpleNamespace(
        id=app_id, budget_id=None, fiscal_year_id=None, data={"ziel": str(node_id)}
    )
    node = SimpleNamespace(id=node_id, parent_id=None, active=True)
    session = _Session({app_id: app, node_id: node}, (fy_id,))
    actions = build_dispatched_actions(
        [{"type": "assignBudgetFromField", "field": "ziel"}],
        application_id=app_id,
        transition_id=uuid4(),
        status_event_id=uuid4(),
    )
    dispatcher = FlowExtrasActionDispatcher(_maker(session))  # type: ignore[arg-type]

    await dispatcher.dispatch(actions)
    assert app.budget_id == node_id
    assert app.fiscal_year_id == fy_id
    assert session.committed == 1
    assert len(calls) == 1

    # A retry of the same action finds the cost center set and changes nothing.
    await dispatcher.dispatch(actions)
    assert session.committed == 1
    assert len(calls) == 1


def test_build_worker_dispatcher_chains_all_handlers() -> None:
    settings = load_settings()
    maker: Any = object()
    chain = build_worker_dispatcher(None, maker, settings)
    assert isinstance(chain, ChainActionDispatcher)
    notify, webhook, extras = chain.dispatchers
    assert isinstance(notify, NotificationActionDispatcher)
    assert isinstance(webhook, WebhookActionDispatcher)
    assert isinstance(extras, FlowExtrasActionDispatcher)
    # Without an arq pool the mails and deliveries stay pending.
    assert notify.queue is None
    assert webhook.queue is None
    assert notify.sessionmaker is maker
    assert webhook.sessionmaker is maker
    assert extras.sessionmaker is maker
    assert notify.settings is settings


def test_build_worker_dispatcher_wraps_the_pool() -> None:
    pool: Any = object()
    chain = build_worker_dispatcher(pool, object())  # type: ignore[arg-type]
    notify, webhook, _extras = chain.dispatchers
    assert notify.queue is not None  # type: ignore[attr-defined]
    assert webhook.queue is not None  # type: ignore[attr-defined]
    assert notify.settings is not None  # type: ignore[attr-defined]
