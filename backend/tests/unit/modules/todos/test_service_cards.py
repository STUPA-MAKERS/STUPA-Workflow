"""``TodoService``: the card detail and the card writes with a scripted session."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

import pytest

from app.modules.tickets.models import TicketEvent
from app.modules.todos import service as svc_mod
from app.modules.todos.lexorank import MAX_LENGTH
from app.modules.todos.links import Resolved
from app.modules.todos.models import (
    TodoAssignee,
    TodoCard,
    TodoCardLabel,
    TodoCheckItem,
    TodoComment,
    TodoEvent,
    TodoLink,
)
from app.modules.todos.schemas import CardCreate, CardMove, CardPatch, CheckItemPatch
from app.modules.todos.service import TodoMail, TodoService
from app.shared.errors import ConflictError, ForbiddenError, NotFoundError, ValidationProblem
from app.shared.people import PersonRef
from tests.unit.modules.todos.fakes import (
    ME,
    OTHER,
    USER,
    FakeAccess,
    FakeLinks,
    ScriptedSession,
    board,
    card,
    column,
    comment,
    event,
    label,
    link,
)

OUT = object()
TICKET = uuid.UUID(int=61)
APP = uuid.UUID(int=31)


def _svc(session: ScriptedSession, links: FakeLinks | None = None, **kw: Any) -> TodoService:
    return TodoService(
        session,  # type: ignore[arg-type]
        access=FakeAccess(**kw),  # type: ignore[arg-type]
        links=links or FakeLinks(),  # type: ignore[arg-type]
    )


def _stub(service: TodoService) -> None:
    async def _detail(*_a: Any) -> Any:
        return OUT

    async def _tiles(cards: Any, _p: Any) -> Any:
        return [OUT for _ in cards]

    service._detail = _detail  # type: ignore[method-assign]
    service.tiles = _tiles  # type: ignore[method-assign]


def _events(session: ScriptedSession) -> list[TodoEvent]:
    return [o for o in session.added if isinstance(o, TodoEvent)]


def _setup(**kw: Any) -> tuple[ScriptedSession, Any, Any, Any, TodoService]:
    b = board()
    col = column(b.id)
    c = card(b, col, **kw)
    session = ScriptedSession()
    session.put(b, col, c)
    service = _svc(session)
    _stub(service)
    return session, b, col, c, service


# -- detail -------------------------------------------------------------------------


async def test_card_404s() -> None:
    session = ScriptedSession(scalar=[None])
    service = _svc(session)
    with pytest.raises(NotFoundError):
        await service.card(uuid.uuid4(), USER)
    orphan = card(board(), column(uuid.uuid4()))
    session.put(orphan)
    with pytest.raises(NotFoundError):
        await service.card(orphan.id, USER)
    with pytest.raises(NotFoundError):
        await service.patch(uuid.uuid4(), CardPatch(version=1), USER)
    session.scalar_q.append(None)
    with pytest.raises(NotFoundError):
        await service.patch(orphan.id, CardPatch(version=1), USER)
    no_account = _svc(ScriptedSession(), me=None)
    with pytest.raises(NotFoundError):
        await no_account.archive_card(orphan.id, USER)


async def test_card_detail_resolves_people_links_events_and_comments(
    people: dict[uuid.UUID, PersonRef],
) -> None:
    people[ME] = PersonRef(principal_id=ME, display_name="Ada")
    people[OTHER] = PersonRef(principal_id=OTHER, display_name="Otto")
    b = board(name="StuPa")
    first, done = column(b.id, "Offen"), column(b.id, "Erledigt", 1, is_done=True)
    lab, unused = label(b.id, "Wichtig"), label(b.id, "Später", "blue")
    c = card(b, first, description_md="**x**")
    app_link = link(c.id, application_id=APP)
    ticket_link = link(c.id, ticket_id=TICKET)
    item = TodoCheckItem(id=uuid.uuid4(), card_id=c.id, text="A", done=True, position=0)
    events = [
        event(c.id, "assigned", {"principalId": str(OTHER), "added": True}),
        event(c.id, "linked", {"linkKind": "application", "targetId": str(APP)}),
        event(c.id, "unlinked", {"linkKind": "ticket", "targetId": str(TICKET)}),
        event(c.id, "linked", {"linkKind": "nope"}),
        event(c.id, "archived", {}, actor=None),
    ]
    mine = comment(c.id, ME, mentions=[str(OTHER), "kaputt"])
    theirs = comment(c.id, OTHER)
    session = ScriptedSession(
        execute=[[(c.id, lab.id)], [(c.id, OTHER)], [(c.id, 1, 1)], [(c.id, 2)]],
        scalars=[
            [app_link, ticket_link],
            [first, done],
            [lab, unused],
            [item],
            events,
            [mine, theirs],
        ],
    )
    session.put(b, c)
    resolved = {("application", APP): Resolved(True, "Antrag", f"/applications/{APP}")}
    out = await _svc(session, FakeLinks(resolved=resolved)).card(c.id, USER)
    assert out.board_name == "StuPa" and out.description_md == "**x**"
    assert [x.name for x in out.labels] == ["Wichtig"]
    assert [x.name for x in out.board_labels] == ["Wichtig", "Später"]
    assert out.created_by.display_name == "Ada"
    assert [ln.accessible for ln in out.links] == [True, False]
    assert out.links[1].title is None and out.primary_link is not None
    assert out.primary_link.title == "Antrag"
    assert out.checklist_items[0].done is True
    assigned, linked, unlinked, broken, archived = out.events
    assert assigned.payload == {
        "person": {"principalId": str(OTHER), "displayName": "Otto"},
        "added": True,
    }
    assert linked.payload["title"] == "Antrag"
    assert unlinked.payload["title"] is None and broken.payload["title"] is None
    assert archived.actor is None and assigned.actor is not None
    own, other = out.comments
    assert own.is_own and not other.is_own
    assert [m.display_name for m in own.mentions] == ["Otto", None]
    assert [a.display_name for a in out.assignees] == ["Otto"]


# -- create -------------------------------------------------------------------------


def _create(b: Any, **kw: Any) -> CardCreate:
    return CardCreate.model_validate({"boardId": str(b.id), "title": " Neu ", **kw})


async def test_create_validates_column_assignees_labels_and_links() -> None:
    b = board()
    col = column(b.id)
    session = ScriptedSession(scalars=[[col], [col], [col], [], [col]])
    session.put(b)
    service = _svc(session, members=[ME])
    with pytest.raises(ValidationProblem) as exc:
        await service.create(_create(b, columnId=str(uuid.uuid4())), USER)
    assert exc.value.code == "column_not_on_board"
    with pytest.raises(ValidationProblem) as exc:
        await service.create(_create(b, assigneeIds=[str(OTHER)]), USER)
    assert exc.value.code == "assignee_not_allowed"
    with pytest.raises(ValidationProblem) as exc:
        await service.create(_create(b, labelIds=[str(uuid.uuid4())]), USER)
    assert exc.value.code == "label_not_on_board"
    with pytest.raises(ValidationProblem) as exc:
        await service.create(_create(b, links=[{"kind": "ticket", "targetId": str(TICKET)}]), USER)
    assert exc.value.code == "link_target_not_found"


async def test_create_in_the_first_column_with_everything() -> None:
    b = board()
    first, other = column(b.id, "Offen"), column(b.id, "B", 1)
    lab = label(b.id)
    last = card(b, first, rank="m")
    session = ScriptedSession(scalars=[[first, other], [lab], [last]])
    session.put(b)
    links = FakeLinks(readable=[("ticket", TICKET)])
    service = _svc(session, links)
    _stub(service)
    payload = _create(
        b,
        dueDate="2026-10-20",
        descriptionMd="d",
        assigneeIds=[str(ME), str(OTHER), str(OTHER)],
        labelIds=[str(lab.id)],
        links=[{"kind": "ticket", "targetId": str(TICKET)}],
    )
    assert await service.create(payload, USER) is OUT
    (new,) = [o for o in session.added if isinstance(o, TodoCard)]
    assert new.title == "Neu" and new.column_id == first.id and new.rank > "m"
    assert new.completed_at is None and new.due_date == date(2026, 10, 20)
    assert len([o for o in session.added if isinstance(o, TodoAssignee)]) == 2
    assert len([o for o in session.added if isinstance(o, TodoCardLabel)]) == 1
    (new_link,) = [o for o in session.added if isinstance(o, TodoLink)]
    assert new_link.ticket_id == TICKET
    assert [e.kind for e in _events(session)] == ["created"]
    assert service.outbox == [TodoMail("assigned", new.id, (OTHER,), ME, None)]


async def test_create_in_the_done_column_completes_and_tells_the_tickets() -> None:
    b = board()
    done = column(b.id, "Erledigt", is_done=True)
    session = ScriptedSession(scalars=[[done], [], [TICKET]])
    session.put(b)
    service = _svc(session)
    _stub(service)
    await service.create(_create(b, columnId=str(done.id), title="x"), USER)
    (new,) = [o for o in session.added if isinstance(o, TodoCard)]
    assert new.completed_at is not None and new.rank == "i"
    (ticket_event,) = [o for o in session.added if isinstance(o, TicketEvent)]
    assert ticket_event.kind == "todo_done" and ticket_event.payload["cardTitle"] == "x"
    assert service.outbox == []


# -- patch --------------------------------------------------------------------------


async def test_patch_checks_the_version() -> None:
    session, _b, _col, c, service = _setup(version=3)
    session.scalar_q.append(c)
    with pytest.raises(ConflictError) as exc:
        await service.patch(c.id, CardPatch(version=2, title="x"), USER)
    assert exc.value.code == "card_version_conflict"


async def test_patch_changes_title_description_and_due_date() -> None:
    session, b, _col, c, service = _setup(title="Alt")
    stamp = b.updated_at
    session.scalar_q.append(c)
    payload = CardPatch.model_validate(
        {"version": 1, "title": " Neu ", "descriptionMd": "d", "dueDate": "2026-11-01"}
    )
    assert await service.patch(c.id, payload, USER) is OUT
    assert (c.title, c.description_md, c.due_date) == ("Neu", "d", date(2026, 11, 1))
    assert c.version == 2 and b.updated_at != stamp
    board_lock, card_lock = (str(st) for st in session.statements[:2])
    assert "FROM todo_board" in board_lock and "FOR UPDATE" in board_lock
    assert "FROM todo_card" in card_lock and "FOR UPDATE" in card_lock
    renamed, due = _events(session)
    assert renamed.payload == {"from": "Alt", "to": "Neu"}
    assert due.payload == {"from": None, "to": "2026-11-01"}


async def test_patch_without_a_change_keeps_the_version() -> None:
    session, _b, _col, c, service = _setup(title="Gleich")
    session.scalar_q.append(c)
    payload = CardPatch.model_validate({"version": 1, "title": "Gleich", "dueDate": None})
    await service.patch(c.id, payload, USER)
    assert c.version == 1 and _events(session) == [] and session.committed == 1
    session.scalar_q.append(c)
    await service.patch(
        c.id, CardPatch.model_validate({"version": 1, "descriptionMd": "neu"}), USER
    )
    assert c.version == 2 and c.title == "Gleich"


# -- move ---------------------------------------------------------------------------


def _move(col: Any, **kw: Any) -> CardMove:
    return CardMove.model_validate({"columnId": str(col.id), **{k: str(v) for k, v in kw.items()}})


async def test_move_needs_a_column_of_the_board() -> None:
    session, _b, col, c, service = _setup()
    session.scalars_q.append([col])
    with pytest.raises(ValidationProblem) as exc:
        await service.move(c.id, _move(column(uuid.uuid4())), USER)
    assert exc.value.code == "column_not_on_board"


async def test_move_within_the_column_between_neighbors() -> None:
    session, b, col, c, service = _setup(rank="z")
    a, d = card(b, col, rank="a"), card(b, col, rank="c")
    session.scalars_q[:] = [[col], [a, d]]
    await service.move(c.id, _move(col, afterId=a.id, beforeId=d.id), USER)
    assert "a" < c.rank < "c"
    assert _events(session) == [] and c.completed_at is None
    session.scalars_q[:] = [[col], [a, d]]
    await service.move(c.id, _move(col, beforeId=a.id), USER)
    assert c.rank < "a"
    session.scalars_q[:] = [[col], [a, d]]
    await service.move(c.id, _move(col, afterId=d.id), USER)
    assert c.rank > "c"


async def test_move_rejects_bad_neighbors() -> None:
    session, b, col, c, service = _setup()
    a, d, e = card(b, col, rank="a"), card(b, col, rank="c"), card(b, col, rank="e")
    for kw in (
        {"afterId": uuid.uuid4()},
        {"beforeId": uuid.uuid4()},
        {"afterId": a.id, "beforeId": e.id},
    ):
        session.scalars_q[:] = [[col], [a, d, e]]
        with pytest.raises(ValidationProblem) as exc:
            await service.move(c.id, _move(col, **kw), USER)
        assert exc.value.code == "rank_neighbors_invalid"


async def test_move_rebalances_on_equal_ranks() -> None:
    session, b, col, c, service = _setup(rank="q")
    a, d = card(b, col, rank="b"), card(b, col, rank="b")
    session.scalars_q[:] = [[col], [a, d]]
    await service.move(c.id, _move(col, afterId=a.id, beforeId=d.id), USER)
    assert a.rank < c.rank < d.rank


async def test_move_into_done_and_back() -> None:
    session, b, col, c, service = _setup()
    done = column(b.id, "Erledigt", 1, is_done=True)
    session.scalars_q[:] = [[col, done], [], [TICKET]]
    await service.move(c.id, _move(done), USER)
    assert c.column_id == done.id and c.completed_at is not None
    # The card is read again after the board lock, so a parallel move is seen.
    assert session.refreshed == [c]
    assert "FOR UPDATE" in str(session.statements[0])
    (moved,) = _events(session)
    assert (
        moved.payload["fromColumnName"] == "Offen" and moved.payload["toColumnName"] == "Erledigt"
    )
    assert any(isinstance(o, TicketEvent) for o in session.added)
    session.scalars_q[:] = [[col, done], []]
    await service.move(c.id, _move(col), USER)
    assert c.column_id == col.id and c.completed_at is None
    # From a column that is gone (no name).
    c.column_id = uuid.uuid4()
    session.scalars_q[:] = [[col, done], []]
    await service.move(c.id, _move(col), USER)
    assert _events(session)[-1].payload["fromColumnName"] == ""


async def test_complete_moves_an_open_card_into_done() -> None:
    session, b, col, c, service = _setup()
    done = column(b.id, "Erledigt", 1, is_done=True)
    tail = card(b, done, rank="k")
    session.scalars_q[:] = [[col], [col, done], [tail], [], [col, done]]
    assert await service.complete(c, b, ME) is False  # no done column
    assert await service.complete(c, b, ME) is True
    assert c.column_id == done.id and c.rank > "k" and c.completed_at is not None
    assert await service.complete(c, b, ME) is False  # done already
    c.column_id = uuid.uuid4()
    session.scalars_q[:] = [[done], [], []]
    assert await service.complete(c, b, None) is True  # type: ignore[arg-type]
    assert _events(session)[-1].payload["fromColumnName"] == ""
    # Every call takes the board lock before it reads the done column.
    locks = [s for s in session.statements if "FOR UPDATE" in str(s)]
    assert len(locks) == 4
    assert session.refreshed == [c] * 4


LONG = "z" * MAX_LENGTH


async def test_move_to_the_end_after_a_long_rank_rebalances() -> None:
    session, b, col, c, service = _setup(rank="a")
    a, d = card(b, col, rank="b"), card(b, col, rank=LONG)
    session.scalars_q[:] = [[col], [a, d]]
    await service.move(c.id, _move(col, afterId=d.id), USER)
    assert a.rank < d.rank < c.rank
    assert max(len(x.rank) for x in (a, c, d)) <= 2


async def test_complete_after_a_long_rank_rebalances_the_done_column() -> None:
    session, b, col, c, service = _setup()
    done = column(b.id, "Erledigt", 1, is_done=True)
    head, tail = card(b, done, rank="a"), card(b, done, rank=LONG)
    session.scalars_q[:] = [[col, done], [head, tail], []]
    assert await service.complete(c, b, ME) is True
    assert head.rank < tail.rank < c.rank
    assert len(c.rank) <= 2


def test_append_keeps_short_ranks_and_rebalances_long_ones() -> None:
    b = board()
    col = column(b.id)
    live = [card(b, col, rank="b"), card(b, col, rank="c")]
    new = [card(b, col, rank=""), card(b, col, rank="")]
    svc_mod._append(live, new)  # pyright: ignore[reportPrivateUsage]
    assert [x.rank for x in live] == ["b", "c"]
    assert "c" < new[0].rank < new[1].rank
    live[1].rank = LONG
    svc_mod._append(live, new)  # pyright: ignore[reportPrivateUsage]
    ranks = [x.rank for x in (*live, *new)]
    assert ranks == sorted(ranks) and len(set(ranks)) == 4
    assert all(len(r) <= 2 for r in ranks)
    svc_mod._append([], new[:1])  # pyright: ignore[reportPrivateUsage]
    assert new[0].rank == "i"


# -- archive ------------------------------------------------------------------------


async def test_archive_and_restore_are_idempotent() -> None:
    session, _b, _col, c, service = _setup()
    await service.archive_card(c.id, USER)
    await service.archive_card(c.id, USER)
    assert c.archived_at is not None and session.committed == 1
    assert await service.restore_card(c.id, USER) is OUT
    assert await service.restore_card(c.id, USER) is OUT
    assert c.archived_at is None and session.committed == 2
    assert [e.kind for e in _events(session)] == ["archived", "restored"]
    assert c.completed_at is None


async def test_restore_in_the_done_column_restarts_the_archive_clock() -> None:
    b = board()
    done = column(b.id, "Erledigt", 1, is_done=True)
    old = svc_mod._now().replace(year=2020)
    c = card(b, done, completed_at=old, archived_at=old)
    session = ScriptedSession()
    session.put(b, done, c)
    service = _svc(session)
    _stub(service)
    await service.restore_card(c.id, USER)
    assert c.archived_at is None
    assert c.completed_at is not None and c.completed_at > old
    assert c.completed_at == c.updated_at


# -- assignees and labels -------------------------------------------------------------


async def test_assignees() -> None:
    session, _b, _col, c, service = _setup()
    session.scalar_q[:] = [c, None, c, OTHER, c]
    await service.add_assignee(c.id, OTHER, USER)
    await service.add_assignee(c.id, OTHER, USER)
    assert len([o for o in session.added if isinstance(o, TodoAssignee)]) == 1
    board_lock, card_lock = (str(st) for st in session.statements[:2])
    assert "FROM todo_board" in board_lock and "FOR UPDATE" in board_lock
    assert "FROM todo_card" in card_lock and "FOR UPDATE" in card_lock
    assert service.outbox == [TodoMail("assigned", c.id, (OTHER,), ME, None)]
    with pytest.raises(ValidationProblem):
        await service.add_assignee(c.id, uuid.uuid4(), USER)
    from tests.unit.modules.todos.fakes import Rows

    session.execute_q[:] = [Rows(rowcount=1), Rows(rowcount=0)]
    await service.remove_assignee(c.id, OTHER, USER)
    await service.remove_assignee(c.id, OTHER, USER)
    assert [e.payload["added"] for e in _events(session)] == [True, False]


async def test_card_labels() -> None:
    session, b, _col, c, service = _setup()
    lab, foreign = label(b.id), label(uuid.uuid4())
    session.put(lab, foreign)
    session.scalar_q[:] = [c, c, c, None, c, lab.id]
    with pytest.raises(ValidationProblem):
        await service.add_card_label(c.id, foreign.id, USER)
    with pytest.raises(ValidationProblem):
        await service.add_card_label(c.id, uuid.uuid4(), USER)
    assert "FOR UPDATE" in str(session.statements[0])
    await service.add_card_label(c.id, lab.id, USER)
    await service.add_card_label(c.id, lab.id, USER)
    assert len([o for o in session.added if isinstance(o, TodoCardLabel)]) == 1
    await service.remove_card_label(c.id, lab.id, USER)
    assert session.committed == 2


# -- checklist ----------------------------------------------------------------------


async def test_checklist() -> None:
    session, _b, _col, c, service = _setup()
    session.scalar_q[:] = [None, 0]
    await service.add_check_item(c.id, " Eins ", USER)
    await service.add_check_item(c.id, "Zwei", USER)
    first, second = [o for o in session.added if isinstance(o, TodoCheckItem)]
    assert (first.text, first.position, second.position) == ("Eins", 0, 1)
    foreign = TodoCheckItem(id=uuid.uuid4(), card_id=uuid.uuid4(), text="x", done=False, position=0)
    session.put(foreign)
    with pytest.raises(NotFoundError):
        await service.patch_check_item(c.id, foreign.id, CheckItemPatch(done=True), USER)
    await service.patch_check_item(c.id, first.id, CheckItemPatch(text=" Eins! ", done=True), USER)
    assert (first.text, first.done) == ("Eins!", True)
    await service.patch_check_item(c.id, first.id, CheckItemPatch(text="Eins!", done=True), USER)
    await service.patch_check_item(c.id, first.id, CheckItemPatch(done=False), USER)
    session.scalars_q.append([first, second])
    await service.patch_check_item(c.id, first.id, CheckItemPatch(position=9), USER)
    assert (second.position, first.position) == (0, 1)
    await service.delete_check_item(c.id, second.id, USER)
    assert session.deleted == [second]
    actions = [e.payload["action"] for e in _events(session)]
    assert actions == ["added", "added", "renamed", "done", "undone", "removed"]


# -- links --------------------------------------------------------------------------


async def test_links() -> None:
    session, _b, _col, c, service = _setup()
    service.links = FakeLinks(readable=[("ticket", TICKET)])  # type: ignore[assignment]
    session.scalar_q[:] = [c, c]
    with pytest.raises(ValidationProblem) as exc:
        await service.add_link(c.id, "todo", c.id, USER)
    assert exc.value.code == "link_self"
    with pytest.raises(ValidationProblem) as exc:
        await service.add_link(c.id, "application", APP, USER)
    assert exc.value.code == "link_target_not_found"
    assert "FOR UPDATE" in str(session.statements[0])
    session.scalar_q[:] = [c, uuid.uuid4(), c, None]
    with pytest.raises(ConflictError) as exc:
        await service.add_link(c.id, "ticket", TICKET, USER)
    assert exc.value.code == "link_exists"
    await service.add_link(c.id, "ticket", TICKET, USER)
    (new,) = [o for o in session.added if isinstance(o, TodoLink)]
    foreign = link(uuid.uuid4(), ticket_id=TICKET)
    session.put(foreign)
    with pytest.raises(NotFoundError):
        await service.remove_link(c.id, foreign.id, USER)
    await service.remove_link(c.id, new.id, USER)
    assert session.deleted == [new]
    assert [e.kind for e in _events(session)] == ["linked", "unlinked"]
    assert _events(session)[1].payload == {"linkKind": "ticket", "targetId": str(TICKET)}


# -- comments -----------------------------------------------------------------------


async def test_comments(people: dict[uuid.UUID, PersonRef]) -> None:
    people[OTHER] = PersonRef(principal_id=OTHER, display_name="Otto")
    session, _b, _col, c, service = _setup()
    with pytest.raises(ValidationProblem) as exc:
        await service.add_comment(c.id, "x", [uuid.uuid4()], USER)
    assert exc.value.code == "mention_not_member"
    body = "Hallo   " + "x" * 300
    out = await service.add_comment(c.id, body, [OTHER, OTHER, ME], USER)
    assert out.is_own and [m.display_name for m in out.mentions] == ["Otto", None]
    (mail,) = service.outbox
    assert mail.kind == "mentioned" and mail.recipients == (OTHER,)
    assert mail.excerpt is not None and len(mail.excerpt) == 200 and mail.excerpt.endswith("…")
    (row,) = [o for o in session.added if isinstance(o, TodoComment)]
    third = uuid.uuid4()
    service.access.member_set.add(third)  # type: ignore[attr-defined]
    await service.edit_comment(c.id, row.id, "kurz", [OTHER, third], USER)
    assert service.outbox[-1].recipients == (third,) and service.outbox[-1].excerpt == "kurz"
    assert row.edited_at is not None
    await service.delete_comment(c.id, row.id, USER)
    assert row.deleted_at is not None
    with pytest.raises(NotFoundError):
        await service.delete_comment(c.id, row.id, USER)
    with pytest.raises(NotFoundError):
        await service.edit_comment(c.id, uuid.uuid4(), "x", [], USER)
    foreign = comment(c.id, OTHER)
    session.put(foreign)
    with pytest.raises(ForbiddenError) as forbidden:
        await service.delete_comment(c.id, foreign.id, USER)
    assert forbidden.value.code == "not_comment_author"
    service.access._me = None  # type: ignore[attr-defined]
    with pytest.raises(ForbiddenError):
        await service.edit_comment(c.id, foreign.id, "x", [], USER)


def test_mail_skips_the_actor_only() -> None:
    service = _svc(ScriptedSession())
    c = card(board(), column(uuid.uuid4()))
    service._mail("assigned", c, [ME], ME)
    assert service.outbox == []
    service._mail("assigned", c, [OTHER, OTHER], ME)
    assert service.outbox[0].recipients == (OTHER,)


def test_small_helpers() -> None:
    assert svc_mod._uuid_of(ME) == ME
    assert svc_mod._uuid_of(str(ME)) == ME
    assert svc_mod._uuid_of("nope") is None
    assert svc_mod._uuid_of(5) is None
    assert svc_mod._ref_of({"linkKind": "ticket", "targetId": str(TICKET)}) == ("ticket", TICKET)
    assert svc_mod._ref_of({"linkKind": "ticket"}) is None
    assert svc_mod._excerpt(" a\n b ") == "a b"
    assert svc_mod.berlin_today(svc_mod._now()) is not None
    assert svc_mod._iso_date(None) is None
