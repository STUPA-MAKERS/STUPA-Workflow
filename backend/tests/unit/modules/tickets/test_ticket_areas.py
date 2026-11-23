"""Unit tests of the Bereiche of the tickets (specs 002700 to 002707, 002715).

They cover the scope of a person, the service of the Bereiche and the Bereich rules of
``TicketService``.

The queues of ``ScriptedSession`` follow the query order of each method.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from app.modules.auth.principal import Principal
from app.modules.gremien.models import Gremium
from app.modules.tickets import access as access_mod
from app.modules.tickets import areas as areas_mod
from app.modules.tickets.access import (
    PLATFORM_ONLY,
    area_scope,
    area_workers,
    works_anywhere,
    works_in,
    works_on_ticket,
    works_on_tickets,
)
from app.modules.tickets.areas import TicketAreaService
from app.modules.tickets.models import (
    PLATFORM_AREA_ID,
    Ticket,
    TicketArea,
    TicketCategory,
    TicketEvent,
)
from app.modules.tickets.schemas import (
    TicketAreaCreate,
    TicketAreaPatch,
    TicketCreate,
    TicketPatch,
)
from app.modules.tickets.service import TicketService
from app.shared.errors import ConflictError, NotFoundError, ValidationProblem
from tests.unit.modules.tickets.fakes import FakeFiles, ScriptedSession

NOW = datetime(2026, 11, 23, tzinfo=UTC)
ME = uuid.uuid4()
GREMIUM_A = uuid.uuid4()
GREMIUM_B = uuid.uuid4()
MANAGER = Principal(sub="mgr", permissions={"ticket.manage"})
MEMBER = Principal(sub="member")


def _area(name: str = "Finanzen", **kw: Any) -> TicketArea:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "name": name,
        "gremium_id": None,
        "platform": False,
        "notify_new": True,
    }
    return TicketArea(**{**base, **kw})


def _platform() -> TicketArea:
    return _area("Plattform", id=PLATFORM_AREA_ID, platform=True)


def _category(area: TicketArea, name: str, position: int = 0) -> TicketCategory:
    return TicketCategory(id=uuid.uuid4(), area_id=area.id, name=name, position=position)


def _ticket(**kw: Any) -> Ticket:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "number": "AAAA0007",
        "area_id": PLATFORM_AREA_ID,
        "category_id": None,
        "kind": "bug",
        "title": "Fehler",
        "body": "Text",
        "status": "new",
        "reporter_principal_id": None,
        "reporter_email": "a@example.org",
        "assignee_id": None,
        "duplicate_of_id": None,
        "context": {},
        "closed_at": None,
        "anonymized_at": None,
        "created_at": NOW,
        "updated_at": NOW,
    }
    return Ticket(**{**base, **kw})


def _svc(session: ScriptedSession) -> TicketService:
    return TicketService(session, files=FakeFiles())  # type: ignore[arg-type]


@pytest.fixture
def audits(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    async def _record(_session: object, **kw: Any) -> None:
        out.append(kw)

    monkeypatch.setattr(areas_mod, "audit_record", _record)
    return out


# ------------------------------------------------------------------ the scope


async def test_ticket_manage_works_in_every_bereich() -> None:
    session = ScriptedSession()
    assert await area_scope(session, MANAGER) is None  # type: ignore[arg-type]
    assert session.statements == []
    assert works_anywhere(None)
    assert works_in(None, uuid.uuid4())


async def test_ticket_work_gives_the_bereiche_of_the_gremium(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[str] = []

    async def _held(_session: object, _principal: Principal, perm: str) -> set[uuid.UUID]:
        asked.append(perm)
        return {GREMIUM_A}

    monkeypatch.setattr(access_mod, "held_gremium_ids", _held)
    area = uuid.uuid4()
    session = ScriptedSession(scalars=[[area]])
    scope = await area_scope(session, MEMBER)  # type: ignore[arg-type]
    assert scope == frozenset({area})
    assert asked == ["ticket.work"]
    assert "ticket_area.gremium_id IN" in str(session.statements[-1])
    assert works_in(scope, area)
    assert not works_in(scope, uuid.uuid4())
    assert await works_on_tickets(ScriptedSession(scalars=[[area]]), MEMBER)  # type: ignore[arg-type]


async def test_no_gremium_right_gives_no_bereich(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _held(*_a: object) -> set[uuid.UUID]:
        return set()

    monkeypatch.setattr(access_mod, "held_gremium_ids", _held)
    session = ScriptedSession()
    scope = await area_scope(session, MEMBER)  # type: ignore[arg-type]
    assert scope == frozenset()
    assert session.statements == []
    assert not works_anywhere(scope)
    assert not await works_on_ticket(session, MEMBER, uuid.uuid4())  # type: ignore[arg-type]


async def test_works_on_ticket_reads_the_bereich_of_the_ticket_or_the_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _held(*_a: object) -> set[uuid.UUID]:
        return {GREMIUM_A}

    monkeypatch.setattr(access_mod, "held_gremium_ids", _held)
    area, other = uuid.uuid4(), uuid.uuid4()
    session = ScriptedSession(scalars=[[area], [area], [area]], scalar=[area, other, None])
    assert await works_on_ticket(session, MEMBER, uuid.uuid4())  # type: ignore[arg-type]
    assert not await works_on_ticket(session, MEMBER, uuid.uuid4(), note=True)  # type: ignore[arg-type]
    assert "ticket_note" in str(session.statements[-1])
    assert not await works_on_ticket(session, MEMBER, uuid.uuid4())  # type: ignore[arg-type]
    assert await works_on_ticket(ScriptedSession(), MANAGER, uuid.uuid4())  # type: ignore[arg-type]


async def test_the_workers_of_a_gremium_bereich_join_the_managers() -> None:
    manager, member = uuid.uuid4(), uuid.uuid4()
    session = ScriptedSession(
        scalars=[[]],
        execute=[
            [(manager, "Mia", "mia@x.org")],
            [(member, "Bo", "bo@x.org"), (manager, "M", None)],
        ],
    )
    area = uuid.uuid4()
    found = await area_workers(session, frozenset({area}))  # type: ignore[arg-type]
    assert sorted(found, key=lambda row: row[1] or "") == [
        (member, "Bo", "bo@x.org"),
        (manager, "Mia", "mia@x.org"),
    ]
    sql = str(session.statements[-1])
    assert "gremium_membership" in sql
    assert "ticket_area.id IN" in sql
    session = ScriptedSession(scalars=[[]], execute=[[], [(member, "Bo", None)]])
    assert await area_workers(session, None, principal_id=member) == [(member, "Bo", None)]  # type: ignore[arg-type]
    assert "ticket_area.id IN" not in str(session.statements[-1])
    session = ScriptedSession(scalars=[[]], execute=[[]])
    assert await area_workers(session, PLATFORM_ONLY) == []  # type: ignore[arg-type]
    assert len(session.statements) == 2


# ------------------------------------------------------------------ the tickets


def test_a_ticket_cannot_be_without_a_bereich() -> None:
    """Spec 002700: the column takes no NULL, and a new row is of ``Plattform``."""
    column = Ticket.__table__.c.area_id
    assert column.nullable is False
    assert column.default.arg == PLATFORM_AREA_ID
    assert TicketArea.__table__.c.name.unique is True


async def test_a_report_of_the_help_menu_lands_in_plattform() -> None:
    """Spec 002701."""
    session = ScriptedSession()
    payload = TicketCreate.model_validate({"kind": "idea", "title": "T", "body": "B"})
    ticket = await _svc(session).create(payload, reporter_id=None, email="a@x.org", pepper="p")
    assert isinstance(ticket, Ticket)
    assert ticket.area_id == PLATFORM_AREA_ID


async def test_a_ticket_of_another_bereich_is_404() -> None:
    """Spec 002703: the right in Gremium B does not open a ticket of Gremium A."""
    area_a, area_b = uuid.uuid4(), uuid.uuid4()
    ticket = _ticket(area_id=area_a, kind=None)
    session = ScriptedSession(scalars=[[], []])
    session.put(ticket)
    service = _svc(session)
    scope_b = frozenset({area_b})
    with pytest.raises(NotFoundError):
        await service.detail(ticket.id, MEMBER, areas=scope_b)
    with pytest.raises(NotFoundError):
        await service.patch(ticket.id, TicketPatch(status="done"), MEMBER, areas=scope_b)
    with pytest.raises(NotFoundError):
        await service.edit_note(ticket.id, uuid.uuid4(), "x", MEMBER, areas=scope_b)
    with pytest.raises(NotFoundError):
        await service.delete_note(ticket.id, uuid.uuid4(), MEMBER, areas=scope_b)
    detail = await service.detail(ticket.id, MEMBER, areas=frozenset({area_a}))
    assert (detail.area_id, detail.kind) == (area_a, None)


async def test_the_list_and_the_counts_keep_to_the_bereiche() -> None:
    """Spec 002715: the scope of the person and the filter both narrow the list."""
    mine, wanted = uuid.uuid4(), uuid.uuid4()
    session = ScriptedSession(scalar=[0], scalars=[[]], execute=[[]])
    await _svc(session).list(areas=frozenset({mine}), area_ids=[wanted])
    params = session.statements[0].compile().params
    assert [mine] in params.values()
    assert [wanted] in params.values()
    await _svc(session).counts(areas=frozenset({mine}))
    assert "ticket.area_id IN" in str(session.statements[-1])
    session = ScriptedSession(execute=[[]])
    await _svc(session).counts()
    assert "area_id" not in str(session.statements[-1])


async def test_an_assignee_needs_the_work_right_in_the_bereich() -> None:
    """Spec 002704: the check asks for the persons of the Bereich of the ticket."""
    area = _area(gremium_id=GREMIUM_A)
    ticket = _ticket(area_id=area.id, kind=None)
    session = ScriptedSession(scalar=[ME], scalars=[[]], execute=[[], []])
    session.put(ticket, area)
    with pytest.raises(ValidationProblem) as exc:
        await _svc(session).patch(ticket.id, TicketPatch(assigneeId=uuid.uuid4()), MANAGER)
    assert exc.value.code == "assignee_not_allowed"
    assert "gremium_membership" in str(session.statements[-1])


async def test_a_kategorie_of_another_bereich_is_422() -> None:
    """Spec 002706."""
    area, other = _area(), _area("Kultur")
    foreign = _category(other, "Raum")
    ticket = _ticket(area_id=area.id, kind=None)
    session = ScriptedSession(scalar=[ME, ME, ME])
    session.put(ticket, area, other, foreign)
    service = _svc(session)
    for patch in (
        TicketPatch(categoryId=foreign.id),
        TicketPatch(categoryId=uuid.uuid4()),
        TicketPatch(kind="bug"),
    ):
        with pytest.raises(ValidationProblem) as exc:
            await service.patch(ticket.id, patch, MANAGER)
        assert exc.value.code == "category_invalid"
    assert ticket.category_id is None


async def test_a_kategorie_is_set_and_cleared_with_an_event() -> None:
    area = _area()
    first = _category(area, "Rechnung")
    ticket = _ticket(area_id=area.id, kind=None)
    session = ScriptedSession(scalar=[ME, ME, ME, ME], scalars=[[], [], [], [], [], []])
    session.put(ticket, area, first)
    service = _svc(session)
    await service.patch(ticket.id, TicketPatch(categoryId=first.id), MANAGER)
    assert ticket.category_id == first.id
    await service.patch(ticket.id, TicketPatch(categoryId=first.id), MANAGER)
    await service.patch(ticket.id, TicketPatch(categoryId=None), MANAGER)
    assert ticket.category_id is None
    events = [e for e in session.added if isinstance(e, TicketEvent)]
    assert [(e.kind, e.payload) for e in events] == [
        ("category", {"from": None, "to": "Rechnung"}),
        ("category", {"from": "Rechnung", "to": None}),
    ]


async def test_a_move_clears_the_kategorie_and_the_foreign_assignee() -> None:
    """Spec 002707: one event, no Kategorie, no assignee without the right there."""
    source, target = _area(), _area("Kultur", gremium_id=GREMIUM_B)
    category = _category(source, "Rechnung")
    assignee = uuid.uuid4()
    ticket = _ticket(area_id=source.id, kind=None, category_id=category.id, assignee_id=assignee)
    session = ScriptedSession(scalar=[ME], scalars=[[], [], []], execute=[[], []])
    session.put(ticket, source, target, category)
    detail = await _svc(session).patch(
        ticket.id, TicketPatch(areaId=target.id), MEMBER, areas=frozenset({source.id})
    )
    assert (ticket.area_id, ticket.category_id, ticket.assignee_id) == (target.id, None, None)
    assert detail.area_id == target.id
    (event,) = [e for e in session.added if isinstance(e, TicketEvent)]
    assert event.kind == "area"
    assert event.payload == {
        "from": str(source.id),
        "to": str(target.id),
        "fromName": "Finanzen",
        "toName": "Kultur",
    }


async def test_a_move_keeps_the_assignee_with_the_right_and_drops_the_kind() -> None:
    target = _area("Kultur")
    assignee = uuid.uuid4()
    ticket = _ticket(assignee_id=assignee)
    session = ScriptedSession(
        scalar=[ME], scalars=[[], [], [], []], execute=[[(assignee, "Ada", None)], []]
    )
    session.put(ticket, _platform(), target)
    await _svc(session).patch(ticket.id, TicketPatch(areaId=target.id), MANAGER)
    assert (ticket.area_id, ticket.kind, ticket.assignee_id) == (target.id, None, assignee)


async def test_a_move_to_the_own_or_an_unknown_bereich() -> None:
    ticket = _ticket()
    session = ScriptedSession(scalar=[ME, ME], scalars=[[], []])
    session.put(ticket, _platform())
    service = _svc(session)
    await service.patch(ticket.id, TicketPatch(areaId=PLATFORM_AREA_ID), MANAGER)
    assert [e for e in session.added if isinstance(e, TicketEvent)] == []
    with pytest.raises(ValidationProblem) as exc:
        await service.patch(ticket.id, TicketPatch(areaId=uuid.uuid4()), MANAGER)
    assert exc.value.code == "area_invalid"


# ------------------------------------------------------------------ the Bereiche


async def test_the_listing_puts_the_kategorien_in_order_and_marks_mine() -> None:
    platform, area = _platform(), _area(gremium_id=GREMIUM_A)
    late, early = _category(area, "B", 1), _category(area, "A", 0)
    session = ScriptedSession(scalars=[[platform, area], [early, late]])
    listed = await TicketAreaService(session).listing(frozenset({area.id}))  # type: ignore[arg-type]
    assert [(a.name, a.platform, a.mine) for a in listed] == [
        ("Plattform", True, False),
        ("Finanzen", False, True),
    ]
    assert [c.name for c in listed[1].categories] == ["A", "B"]
    assert listed[1].gremium_id == GREMIUM_A
    assert listed[0].categories == ()


async def test_create_stores_the_bereich_with_its_kategorien(
    audits: list[dict[str, Any]],
) -> None:
    gremium = Gremium(id=GREMIUM_A, name="AStA", slug="asta")
    session = ScriptedSession(execute=[[(PLATFORM_AREA_ID, "Plattform")]], scalars=[[]])
    session.put(gremium)
    payload = TicketAreaCreate.model_validate(
        {
            "name": " Finanzen ",
            "gremiumId": str(GREMIUM_A),
            "categories": [{"name": "A"}, {"name": " B "}],
        }
    )
    out = await TicketAreaService(session).create(payload, "adm")  # type: ignore[arg-type]
    area = next(o for o in session.added if isinstance(o, TicketArea))
    assert (area.name, area.gremium_id, area.platform) == ("Finanzen", GREMIUM_A, False)
    stored = [o for o in session.added if isinstance(o, TicketCategory)]
    assert [(c.name, c.position, c.area_id) for c in stored] == [
        ("A", 0, area.id),
        ("B", 1, area.id),
    ]
    assert out.name == "Finanzen"
    assert audits[0]["target_type"] == "ticket_area"
    assert audits[0]["actor"] == "adm"


async def test_create_refuses_a_used_name_an_unknown_gremium_and_bad_kategorien(
    audits: list[dict[str, Any]],
) -> None:
    session = ScriptedSession(execute=[[(PLATFORM_AREA_ID, "Plattform")], []])
    service = TicketAreaService(session)  # type: ignore[arg-type]
    with pytest.raises(ConflictError) as taken:
        await service.create(TicketAreaCreate(name="plattform"), "adm")
    assert taken.value.code == "ticket_area_name_taken"
    with pytest.raises(ValidationProblem):
        await service.create(TicketAreaCreate(name="X", gremiumId=uuid.uuid4()), "adm")
    twice = TicketAreaCreate.model_validate(
        {"name": "Y", "categories": [{"name": "a"}, {"name": "A"}]}
    )
    with pytest.raises(ValidationProblem) as exc:
        await service.create(twice, "adm")
    assert exc.value.code == "ticket_categories_invalid"
    blank = TicketAreaCreate.model_validate({"name": "Y", "categories": [{"name": "  "}]})
    with pytest.raises(ValidationProblem):
        await service.create(blank, "adm")
    assert audits == []


async def test_plattform_keeps_its_name_its_kategorien_and_takes_the_switch(
    audits: list[dict[str, Any]],
) -> None:
    """Specs 002701, 002702 and 002706."""
    platform = _platform()
    session = ScriptedSession(scalars=[[]])
    session.put(platform)
    service = TicketAreaService(session)  # type: ignore[arg-type]
    fixed = (
        {"name": "Helpdesk"},
        {"gremiumId": str(GREMIUM_A)},
        {"categories": [{"name": "Fehlerchen"}]},
    )
    for body in fixed:
        with pytest.raises(ConflictError) as exc:
            await service.patch(PLATFORM_AREA_ID, TicketAreaPatch.model_validate(body), "adm")
        assert exc.value.code == "ticket_area_platform_fixed"
    out = await service.patch(PLATFORM_AREA_ID, TicketAreaPatch(notifyNew=False), "adm")
    assert (platform.notify_new, out.notify_new) == (False, False)
    with pytest.raises(ConflictError) as exc:
        await service.delete(PLATFORM_AREA_ID, "adm")
    assert exc.value.code == "ticket_area_platform_fixed"
    assert session.deleted == []
    assert len(audits) == 1


async def test_patch_changes_name_gremium_and_the_list_of_kategorien(
    audits: list[dict[str, Any]],
) -> None:
    area = _area(gremium_id=GREMIUM_A)
    keep, drop = _category(area, "Alt", 0), _category(area, "Weg", 1)
    session = ScriptedSession(
        execute=[[(area.id, "Finanzen"), (PLATFORM_AREA_ID, "Plattform")], []],
        scalars=[[keep, drop], [keep]],
    )
    session.put(area)
    body = {
        "name": "Kasse",
        "gremiumId": None,
        "categories": [{"name": "Neu"}, {"id": str(keep.id), "name": "Alt 2"}],
    }
    out = await TicketAreaService(session).patch(  # type: ignore[arg-type]
        area.id, TicketAreaPatch.model_validate(body), "adm"
    )
    assert (area.name, area.gremium_id) == ("Kasse", None)
    assert (keep.name, keep.position) == ("Alt 2", 1)
    (new,) = [o for o in session.added if isinstance(o, TicketCategory)]
    assert (new.name, new.position) == ("Neu", 0)
    assert "DELETE FROM ticket_category" in str(session.statements[2])
    assert out.name == "Kasse"
    assert audits[0]["data"] == {"fields": ["categories", "gremium_id", "name"]}


async def test_patch_refuses_foreign_kategorien_and_unknown_bereiche(
    audits: list[dict[str, Any]],
) -> None:
    area = _area()
    own = _category(area, "A")
    service = TicketAreaService(ScriptedSession())  # type: ignore[arg-type]
    with pytest.raises(NotFoundError):
        await service.patch(uuid.uuid4(), TicketAreaPatch(notifyNew=True), "adm")
    for wanted in (
        [{"id": str(uuid.uuid4()), "name": "X"}],
        [{"id": str(own.id), "name": "A"}, {"id": str(own.id), "name": "B"}],
    ):
        session = ScriptedSession(scalars=[[own]])
        session.put(area)
        with pytest.raises(ValidationProblem) as exc:
            await TicketAreaService(session).patch(  # type: ignore[arg-type]
                area.id, TicketAreaPatch.model_validate({"categories": wanted}), "adm"
            )
        assert exc.value.code == "ticket_categories_invalid"
    assert audits == []


async def test_delete_refuses_a_bereich_with_a_ticket(audits: list[dict[str, Any]]) -> None:
    """Spec 002705."""
    area = _area()
    session = ScriptedSession(scalar=[uuid.uuid4(), None])
    session.put(area)
    service = TicketAreaService(session)  # type: ignore[arg-type]
    with pytest.raises(ConflictError) as exc:
        await service.delete(area.id, "adm")
    assert exc.value.code == "ticket_area_has_tickets"
    assert session.deleted == []
    await service.delete(area.id, "adm")
    assert session.deleted == [area]
    assert audits[0]["data"] == {"deleted": True, "name": "Finanzen"}
