"""Events: totals, decisions, series and the one-Event rule (specs 000479-000483)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import true

from app.modules.todos import events
from app.modules.todos.models import TodoCardEvent
from app.shared.errors import ConflictError
from tests.unit.modules.todos.fakes import ScriptedSession, board, card, column, link

CARD = uuid.UUID(int=100)
EMPTY = uuid.UUID(int=101)
A1, A2, A3, A4 = (uuid.UUID(int=n) for n in (11, 12, 13, 14))
E1, E2, E3, E4 = (uuid.UUID(int=n) for n in (21, 22, 23, 24))
V1, V2, V3 = (uuid.UUID(int=n) for n in (31, 32, 33))
T1 = datetime(2026, 5, 1, tzinfo=UTC)
T2 = datetime(2026, 6, 1, tzinfo=UTC)
T3 = datetime(2026, 7, 1, tzinfo=UTC)


async def test_event_rows_by_card() -> None:
    session = ScriptedSession()
    assert await events.event_rows(session, []) == {}
    assert session.statements == []
    row = TodoCardEvent(card_id=CARD, series_id=None)
    row.id = CARD
    session.put(row)
    assert await events.event_rows(session, [CARD]) == {CARD: row}


async def test_series_names_skip_none_and_map_ids() -> None:
    session = ScriptedSession(execute=[[(V1, "Sommerfest")]])
    assert await events.series_names(session, [None]) == {}
    assert session.statements == []
    assert await events.series_names(session, [V1, None, V1]) == {V1: "Sommerfest"}


async def test_totals_without_cards_or_links() -> None:
    session = ScriptedSession(scalars=[[]])
    assert await events.totals(session, []) == {}
    out = await events.totals(session, [EMPTY])
    assert out[EMPTY] == events.Totals()
    assert out[EMPTY].balance == Decimal("0.00")
    assert len(session.statements) == 1


async def test_totals_sum_applications_and_bookings() -> None:
    links = [
        link(CARD, application_id=A1),
        link(CARD, application_id=A2),
        link(CARD, application_id=A3),
        link(CARD, application_id=A4),
        link(CARD, expense_id=E1),
        link(CARD, expense_id=E2),
        link(CARD, expense_id=E3),
        link(CARD, expense_id=E4),
    ]
    session = ScriptedSession(
        scalars=[links, [A1, A3]],
        execute=[
            [
                (A1, Decimal("100.00"), Decimal("80.00")),
                (A2, Decimal("50.00"), None),
                (A3, None, None),
            ],
            [
                (E1, "expense", Decimal("20.00"), None),
                (E2, "expense", Decimal("5.00"), E1),
                (E3, "income", Decimal("70.00"), None),
            ],
        ],
    )
    out = await events.totals(session, [CARD, EMPTY])
    got = out[CARD]
    assert got.requested == Decimal("150.00")
    assert got.approved == Decimal("80.00")
    assert got.expenses == Decimal("20.00")
    assert got.income == Decimal("70.00")
    assert got.balance == Decimal("50.00")
    assert out[EMPTY] == events.Totals()


async def test_totals_approved_falls_back_to_the_requested_amount() -> None:
    session = ScriptedSession(
        scalars=[[link(CARD, application_id=A1)], [A1]],
        execute=[[(A1, Decimal("40.00"), None)]],
    )
    got = (await events.totals(session, [CARD]))[CARD]
    assert got.requested == got.approved == Decimal("40.00")


async def test_totals_count_a_sub_booking_alone_when_its_parent_is_not_linked() -> None:
    session = ScriptedSession(
        scalars=[[link(CARD, expense_id=E2)]],
        execute=[[(E2, "expense", Decimal("5.00"), E1)]],
    )
    assert (await events.totals(session, [CARD]))[CARD].expenses == Decimal("5.00")


def _app(app_id: uuid.UUID, title: str | None, amount: str | None) -> SimpleNamespace:
    return SimpleNamespace(
        id=app_id,
        data={"title": title} if title else None,
        amount=Decimal(amount) if amount else None,
    )


def _decision(
    vote_id: uuid.UUID | None, at: datetime, approved: str | None, conditions: list[str] | None
) -> SimpleNamespace:
    return SimpleNamespace(
        vote_id=vote_id,
        decided_at=at,
        approved_amount=Decimal(approved) if approved else None,
        conditions=conditions,
    )


def _vote(
    vote_id: uuid.UUID,
    *,
    question: str | None = None,
    application_id: uuid.UUID | None = None,
    closed_at: datetime | None = None,
    result: str = "passed",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=vote_id,
        question=question,
        application_id=application_id,
        closed_at=closed_at,
        result=result,
    )


async def test_decisions_without_links() -> None:
    session = ScriptedSession(scalars=[[]])
    assert await events.decisions(session, CARD) == []
    assert len(session.statements) == 1


async def test_decisions_merge_votes_and_order_newest_first() -> None:
    links = [
        link(CARD, application_id=A1),
        link(CARD, application_id=A2),
        link(CARD, agenda_item_id=uuid.uuid4()),
        link(CARD, vote_id=V2),
    ]
    v2 = _vote(V2, application_id=A4, closed_at=T3, result="passed")
    session = ScriptedSession(
        scalars=[links],
        execute=[
            [
                (
                    _app(A1, " Sommerfest ", "100.00"),
                    _decision(V1, T2, "80.00", ["Beleg"]),
                    "StuPa",
                ),
                (_app(A2, None, "30.00"), _decision(None, T1, None, None), None),
            ],
            [
                (_vote(V1, question="Antrag 1", closed_at=T2), "StuPa", "TOP 1"),
                (v2, "AStA", "TOP 2"),
                (v2, "AStA", "TOP 2"),
                (_vote(V3, result="rejected"), None, "TOP 3"),
            ],
            [(A4, {"title": "Antrag 4"})],
        ],
    )
    out = await events.decisions(session, CARD)
    assert [(d.kind, d.target_id) for d in out] == [
        ("vote", V2),
        ("decision", A1),
        ("decision", A2),
        ("vote", V3),
    ]
    vote2, app1, app2, vote3 = out
    assert (vote2.title, vote2.meeting_title, vote2.result, vote2.amount) == (
        "Antrag 4",
        "AStA",
        "passed",
        None,
    )
    assert (app1.title, app1.amount, app1.conditions, app1.result) == (
        "Sommerfest",
        Decimal("80.00"),
        ["Beleg"],
        "passed",
    )
    assert (app2.title, app2.amount, app2.conditions, app2.meeting_title) == (
        "",
        Decimal("30.00"),
        [],
        None,
    )
    assert (vote3.title, vote3.result, vote3.decided_at) == ("TOP 3", "rejected", None)


async def test_decisions_of_votes_only_use_question_and_skip_title_query() -> None:
    session = ScriptedSession(
        scalars=[[link(CARD, vote_id=V1)]],
        execute=[[(_vote(V1, question="Budget?", closed_at=T1), None, None)]],
    )
    (only,) = await events.decisions(session, CARD)
    assert (only.kind, only.title, only.target_id) == ("vote", "Budget?", V1)
    assert len(session.statements) == 2


async def test_decisions_vote_without_any_title() -> None:
    session = ScriptedSession(
        scalars=[[link(CARD, agenda_item_id=uuid.uuid4())]],
        execute=[[(_vote(V1), None, None)]],
    )
    (only,) = await events.decisions(session, CARD)
    assert only.title == ""


async def test_editions_without_series() -> None:
    session = ScriptedSession()
    b = board()
    c = card(b, column(b.id))
    assert await events.editions(session, c, None, true()) == ([], 0)
    assert session.statements == []


async def test_editions_count_the_hidden_rest() -> None:
    b = board()
    col = column(b.id)
    c = card(b, col)
    others = [(card(b, col), b, TodoCardEvent()), (card(b, col), b, TodoCardEvent())]
    session = ScriptedSession(scalar=[5], execute=[others])
    rows, rest = await events.editions(session, c, uuid.uuid4(), true())
    assert rows == others
    assert rest == 3


async def test_editions_rest_never_negative() -> None:
    b = board()
    col = column(b.id)
    c = card(b, col)
    session = ScriptedSession(scalar=[None], execute=[[(card(b, col), b, TodoCardEvent())]])
    rows, rest = await events.editions(session, c, uuid.uuid4(), true())
    assert len(rows) == 1
    assert rest == 0


async def test_check_one_event_ignores_kinds_without_the_rule() -> None:
    session = ScriptedSession()
    await events.check_one_event(session, CARD, [("meeting", V1), ("vote", V2)])
    assert session.statements == []


async def test_check_one_event_passes_a_free_element() -> None:
    session = ScriptedSession(scalar=[None])
    await events.check_one_event(session, CARD, [("application", A1), ("expense", E1)])
    assert len(session.statements) == 1


async def test_check_one_event_refuses_a_taken_element() -> None:
    session = ScriptedSession(scalar=[uuid.uuid4()])
    with pytest.raises(ConflictError) as err:
        await events.check_one_event(session, CARD, [("invoice", E3), ("todo", CARD)])
    assert err.value.code == "event_link_taken"
    assert err.value.status == 409


def test_balance_text_has_two_places() -> None:
    assert events.balance_text(Decimal("5")) == "5.00"
    assert events.balance_text(Decimal("-12.5")) == "-12.50"
