"""The cancel of an open repeat gives the application back its first decision.

``restore_repeated_decision`` undoes the move back of a repeat. It does nothing for a
vote that is no repeat, for a repeat that never moved the application, and for an
application that left the vote state by another way.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.modules.flow.service import FlowService
from app.modules.voting.repeat import (
    REPEAT_CANCELLED_NOTE,
    REPEAT_NOTE,
    restore_repeated_decision,
)
from tests._support.flow_fakes import fake_session, result

_CLOSED = datetime(2026, 5, 4, 18, 0, tzinfo=UTC)


def _event(vote_state: UUID, decided_state: UUID | None, **over: Any) -> SimpleNamespace:
    """Build the status event of a move back that came after the close."""
    return SimpleNamespace(
        **{
            "id": uuid4(),
            "note": REPEAT_NOTE,
            "to_state_id": vote_state,
            "from_state_id": decided_state,
            "at": _CLOSED + timedelta(minutes=5),
            **over,
        }
    )


def _session(event: object, current: UUID | None, entry: object = None) -> Any:
    """Build a session with the closed source vote, the event, the state and the entry."""
    db = fake_session(
        result(*([event] if event is not None else [])),
        result(*([entry] if entry is not None else [])),
    )
    db.get_results = [SimpleNamespace(closed_at=_CLOSED)]
    db.scalar_results = [current]
    return db


@pytest.fixture
def reverts(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Record the calls of ``FlowService.revert_status``."""
    calls: list[dict[str, Any]] = []

    async def _revert_status(self: FlowService, application_id: UUID, **kwargs: Any) -> UUID:
        calls.append({"application_id": application_id, **kwargs})
        return uuid4()

    monkeypatch.setattr(FlowService, "revert_status", _revert_status)
    return calls


async def test_a_vote_that_is_no_repeat_restores_nothing(reverts: list[dict[str, Any]]) -> None:
    assert await restore_repeated_decision(fake_session(), uuid4(), None, actor="p") is False
    assert reverts == []


async def test_a_repeat_without_application_restores_nothing(
    reverts: list[dict[str, Any]],
) -> None:
    db = fake_session()
    db.get_results = [SimpleNamespace(closed_at=_CLOSED)]
    assert await restore_repeated_decision(db, None, uuid4(), actor="p") is False
    assert reverts == []


@pytest.mark.parametrize("source", [None, SimpleNamespace(closed_at=None)])
async def test_a_source_that_is_not_closed_restores_nothing(
    source: object, reverts: list[dict[str, Any]]
) -> None:
    db = fake_session()
    db.get_results = [source]
    assert await restore_repeated_decision(db, uuid4(), uuid4(), actor="p") is False
    assert reverts == []


@pytest.mark.parametrize(
    "case", ["no_event", "other_note", "left_state", "no_from_state", "older_move"]
)
async def test_a_move_back_that_is_not_of_this_repeat_restores_nothing(
    case: str, reverts: list[dict[str, Any]]
) -> None:
    vote_state, decided = uuid4(), uuid4()
    events = {
        "no_event": None,
        "other_note": _event(vote_state, decided, note="vote:rejected"),
        "left_state": _event(uuid4(), decided),
        "no_from_state": _event(vote_state, None),
        "older_move": _event(vote_state, decided, at=_CLOSED - timedelta(minutes=5)),
    }
    db = _session(events[case], vote_state)
    assert await restore_repeated_decision(db, uuid4(), uuid4(), actor="p") is False
    assert reverts == []


async def test_a_move_back_without_audit_entry_restores_nothing(
    reverts: list[dict[str, Any]],
) -> None:
    vote_state = uuid4()
    db = _session(_event(vote_state, uuid4()), vote_state)
    assert await restore_repeated_decision(db, uuid4(), uuid4(), actor="p") is False
    assert reverts == []


async def test_the_restore_moves_back_and_swaps_the_decisions(
    reverts: list[dict[str, Any]],
) -> None:
    vote_state, decided, app_id = uuid4(), uuid4(), uuid4()
    first, before = uuid4(), uuid4()
    event = _event(vote_state, decided)
    entry = SimpleNamespace(
        id=41, data={"decisionUndoneId": str(first), "decisionRestoredId": str(before)}
    )
    db = _session(event, vote_state, entry)
    assert await restore_repeated_decision(db, app_id, uuid4(), actor="p") is True
    [call] = reverts
    assert call["application_id"] == app_id
    assert call["from_state_id"] == decided and call["to_state_id"] == vote_state
    assert call["reverted_audit_id"] == 41
    assert call["reverted_status_event_id"] == event.id
    assert call["note"] == REPEAT_CANCELLED_NOTE and call["actor"] == "p"
    assert call["decision_swap"].restored_id == first
    assert call["decision_swap"].undone_id == before


@pytest.mark.parametrize("data", [None, {}, {"decisionUndoneId": None}])
async def test_the_restore_without_a_first_decision(
    data: dict[str, Any] | None, reverts: list[dict[str, Any]]
) -> None:
    vote_state = uuid4()
    db = _session(_event(vote_state, uuid4()), vote_state, SimpleNamespace(id=5, data=data))
    assert await restore_repeated_decision(db, uuid4(), uuid4(), actor="p") is True
    [call] = reverts
    swap = call["decision_swap"]
    assert swap is None or (swap.restored_id is None and swap.undone_id is None)
