"""Integration (real Postgres): @-mentions in the comments of an application.

The mentionable persons are exactly the readers of the internal comments: the holders
of ``application.read`` and ``application.read_all``, the active members of the
committee Gremien (budget view Gremium on an ancestor, vote Gremium, the Gremium of a
meeting that voted) and the creator with a member right. A creator without one, a
member of another Gremium, an inactive and an erased account drop out.
``committee_gremium_ids`` and ``_committee_can_read`` agree on every member.

The comment service refuses a mention outside the set and any mention without
``may_mention`` (422 ``mention_not_member``), removes duplicates, reports the added
mentions, keeps them on an edit without a list and hides them in the applicant view.
The account merge rewrites the stored ids of the comments and the ticket notes. The
mention mails reach the new mentions without the actor and without an opt-out, one
mail per person, with the link to the comment or the note.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.admin.models import ApplicationType, Gremium, GremiumMembership, GremiumRole
from app.modules.applications.access import _committee_can_read, committee_gremium_ids
from app.modules.applications.mentions import mentionable_people
from app.modules.applications.models import Application, Comment
from app.modules.applications.schemas import ApplicationCreate, CommentOut
from app.modules.applications.service import ApplicationsService
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.models import Role, RoleAssignment, RolePermission
from app.modules.auth.principal import Principal
from app.modules.budget.tree_models import Budget
from app.modules.flow.models import FlowVersion, State
from app.modules.forms.schemas import FormVersionCreate
from app.modules.forms.service import FormsService
from app.modules.livevote.models import Meeting
from app.modules.notifications.mail import MailMessage, compute_idempotency_key
from app.modules.notifications.mentions import send_comment_mentions, send_ticket_mentions
from app.modules.notifications.models import NotificationPreference
from app.modules.tickets.models import Ticket, TicketNote
from app.modules.todos.merge import rewrite_mentions
from app.modules.voting.models import Vote
from app.settings import load_settings
from app.shared.config_schemas import FormFieldDef
from app.shared.errors import ValidationProblem
from tests.integration.conftest import clear_privacy_tables

pytestmark = pytest.mark.integration


@pytest.fixture
async def session(migrated: tuple[str, str], engine: Engine) -> AsyncIterator[AsyncSession]:
    clear_privacy_tables(engine)
    eng = create_async_engine(migrated[1])
    maker = async_sessionmaker(eng, expire_on_commit=False)
    async with maker() as s:
        yield s
    await eng.dispose()
    clear_privacy_tables(engine)


@dataclass
class _World:
    ids: dict[str, uuid.UUID]
    subs: dict[str, str]
    gremien: dict[str, uuid.UUID]
    app: uuid.UUID
    plain_app: uuid.UUID


async def _role(session: AsyncSession, perm: str) -> uuid.UUID:
    role = Role(key=f"mention_{uuid.uuid4().hex[:8]}", name_i18n={})
    session.add(role)
    await session.flush()
    session.add(RolePermission(role_id=role.id, permission=perm))
    return role.id


async def _seed(session: AsyncSession) -> _World:
    tag = uuid.uuid4().hex[:8]
    gremien = {
        k: Gremium(name=k, slug=f"{k}-{tag}") for k in ("vote", "view", "meet", "other")
    }
    session.add_all(gremien.values())
    await session.flush()
    roles = {
        k: GremiumRole(gremium_id=g.id, key="member", name_i18n={}, permissions=["vote.cast"])
        for k, g in gremien.items()
    }
    session.add_all(roles.values())

    names = {
        "reader": "Rita Reader",
        "read_all": "Anna Alles",
        "vote": "Vera Vote",
        "view": "Viktor View",
        "meet": "Mona Meet",
        "other": "Otto Other",
        "creator": "Carla Creator",
        "plain": "Paul Plain",
        "inactive": "Ina Inactive",
        "erased": None,
    }
    rows = {
        k: PrincipalRow(
            sub=f"{k}-{tag}",
            display_name=name,
            email=None if k == "erased" else f"{k}-{tag}@example.org",
            active=k != "inactive",
        )
        for k, name in names.items()
    }
    session.add_all(rows.values())
    await session.flush()
    read = await _role(session, "application.read")
    read_all = await _role(session, "application.read_all")
    manage = await _role(session, "application.manage")
    for key, role in (
        ("reader", read),
        ("read_all", read_all),
        ("creator", manage),
        ("inactive", read),
        ("erased", read),
    ):
        session.add(RoleAssignment(principal_id=rows[key].id, role_id=role))
    for key in ("vote", "view", "meet", "other"):
        session.add(
            GremiumMembership(
                principal_id=rows[key].id,
                gremium_id=gremien[key].id,
                gremium_role_id=roles[key].id,
            )
        )
    app_type = ApplicationType(
        gremium_id=gremien["vote"].id, key=f"t-{tag}", name_i18n={}, has_budget=True
    )
    session.add(app_type)
    await session.commit()
    await FormsService(session).create_form_version(
        app_type.id,
        FormVersionCreate(
            fields=[FormFieldDef(key="title", type="text", label={"de": "Titel"}, required=True)],
            activate=True,
        ),
        "tester",
    )
    flow = FlowVersion(version=1, active=True, editor_layout={})
    session.add(flow)
    await session.flush()
    session.add(
        State(flow_version_id=flow.id, key="draft", label_i18n={"de": "E"}, is_initial=True)
    )
    top = Budget(
        parent_id=None,
        key=f"VS{tag}",
        path_key=f"VS{tag}",
        name="Top",
        view_gremium_id=gremien["view"].id,
    )
    session.add(top)
    await session.flush()
    leaf = Budget(parent_id=top.id, key="800", path_key=f"VS{tag}-800", name="Leaf")
    session.add(leaf)
    await session.commit()

    svc = ApplicationsService(session)

    def _payload() -> ApplicationCreate:
        return ApplicationCreate.model_validate(
            {
                "typeId": str(app_type.id),
                "data": {"title": "Antrag"},
                "applicantEmail": "x@example.org",
            }
        )

    app, _ = await svc.create(_payload(), actor=rows["creator"].sub)
    plain_app, _ = await svc.create(_payload(), actor=rows["plain"].sub)
    app.budget_id = leaf.id
    app.vote_gremium_id = gremien["vote"].id
    meeting = Meeting(gremium_id=gremien["meet"].id, title="Sitzung", status="closed")
    session.add(meeting)
    await session.flush()
    session.add(
        Vote(
            application_id=app.id,
            meeting_id=meeting.id,
            eligible_group=str(gremien["meet"].id),
            config={},
            status="closed",
            result="passed",
        )
    )
    await session.commit()
    return _World(
        ids={k: r.id for k, r in rows.items()},
        subs={k: r.sub for k, r in rows.items()},
        gremien={k: g.id for k, g in gremien.items()},
        app=app.id,
        plain_app=plain_app.id,
    )


async def test_the_mentionable_persons_are_the_internal_readers(session: AsyncSession) -> None:
    w = await _seed(session)
    people = await mentionable_people(session, w.app)
    assert [p.display_name for p in people] == [
        "Anna Alles",
        "Carla Creator",
        "Mona Meet",
        "Rita Reader",
        "Vera Vote",
        "Viktor View",
    ]
    assert {p.principal_id for p in people} == {
        w.ids[k] for k in ("read_all", "creator", "meet", "reader", "vote", "view")
    }
    # The creator without a member right reads as the applicant: no mention.
    plain = {p.principal_id for p in await mentionable_people(session, w.plain_app)}
    assert plain == {w.ids["reader"], w.ids["read_all"]}


async def test_the_committee_set_mirrors_the_read_check(session: AsyncSession) -> None:
    w = await _seed(session)
    gremien = await committee_gremium_ids(session, w.app)
    assert gremien == {w.gremien["vote"], w.gremien["view"], w.gremien["meet"]}
    assert await committee_gremium_ids(session, w.plain_app) == set()
    assert await committee_gremium_ids(session, uuid.uuid4()) == set()
    for key in ("vote", "view", "meet", "other"):
        member = Principal(sub=w.subs[key])
        assert await _committee_can_read(session, w.app, member) is (key != "other")


async def _add(
    svc: ApplicationsService,
    w: _World,
    mentions: list[uuid.UUID],
    *,
    may_mention: bool = True,
    visibility: str = "internal",
) -> CommentOut:
    return await svc.add_comment(
        w.app,
        author=w.subs["reader"],
        author_kind="principal",
        body="@Vera bitte",
        visibility=visibility,
        mentions=mentions,
        may_mention=may_mention,
    )


async def _edit(
    svc: ApplicationsService, w: _World, comment_id: uuid.UUID, mentions: list[uuid.UUID] | None
) -> CommentOut:
    return await svc.update_comment(
        w.app,
        comment_id,
        body="neu",
        actor=w.subs["reader"],
        viewer_sub=w.subs["reader"],
        viewer_is_applicant=False,
        can_manage=False,
        mentions=mentions,
        may_mention=True,
    )


async def test_the_comment_checks_stores_and_hides_the_mentions(session: AsyncSession) -> None:
    w = await _seed(session)
    svc = ApplicationsService(session)
    with pytest.raises(ValidationProblem) as err:
        await _add(svc, w, [w.ids["other"]])
    assert err.value.code == "mention_not_member"
    assert err.value.errors is not None and err.value.errors[0].field == "mentions"
    with pytest.raises(ValidationProblem) as err:
        await _add(svc, w, [w.ids["vote"]], may_mention=False)
    assert err.value.code == "mention_not_member"

    out = await _add(svc, w, [w.ids["vote"], w.ids["vote"], w.ids["reader"]])
    assert [m.principal_id for m in out.mentions] == [w.ids["vote"], w.ids["reader"]]
    assert list(svc.added_mentions) == [w.ids["vote"], w.ids["reader"]]
    stored = await session.scalar(select(Comment.mentions).where(Comment.id == out.id))
    assert stored == [str(w.ids["vote"]), str(w.ids["reader"])]

    kept = await _edit(svc, w, out.id, None)
    assert [m.principal_id for m in kept.mentions] == [w.ids["vote"], w.ids["reader"]]
    assert list(svc.added_mentions) == []
    changed = await _edit(svc, w, out.id, [w.ids["meet"], w.ids["vote"]])
    assert [m.principal_id for m in changed.mentions] == [w.ids["meet"], w.ids["vote"]]
    assert list(svc.added_mentions) == [w.ids["meet"]]

    member_view = await svc.list_comments(w.app, include_internal=True)
    assert [m.display_name for m in member_view[0].mentions] == ["Mona Meet", "Vera Vote"]
    # The applicant reads a public body, so a public comment names no member.
    with pytest.raises(ValidationProblem) as err:
        await _add(svc, w, [w.ids["vote"]], visibility="public")
    assert err.value.code == "mention_not_member"
    public = await _add(svc, w, [], visibility="public")
    with pytest.raises(ValidationProblem):
        await _edit(svc, w, public.id, [w.ids["vote"]])
    applicant_view = await svc.list_comments(
        w.app, include_internal=False, applicant_view=True
    )
    assert [c.id for c in applicant_view] == [public.id]
    assert applicant_view[0].mentions == []


async def test_the_merge_rewrites_the_mentions_of_comments_and_notes(
    session: AsyncSession,
) -> None:
    w = await _seed(session)
    old, new = w.ids["vote"], w.ids["view"]
    session.add(
        Comment(
            application_id=w.app,
            author=w.subs["reader"],
            author_kind="principal",
            body="x",
            visibility="internal",
            mentions=[str(old), str(new)],
        )
    )
    ticket = Ticket(kind="bug", title="t", body="b", reporter_email="r@example.org")
    session.add(ticket)
    await session.flush()
    session.add(TicketNote(ticket_id=ticket.id, author_id=w.ids["reader"], body="n",
                           mentions=[str(old)]))
    await session.commit()
    assert await rewrite_mentions(session, old, new, apply=False, table="comment") == 1
    assert await rewrite_mentions(session, old, new, apply=False, table="ticket_note") == 1
    assert await rewrite_mentions(session, old, new, apply=True, table="comment") == 1
    assert await rewrite_mentions(session, old, new, apply=True, table="ticket_note") == 1
    await session.commit()
    assert (await session.scalars(select(Comment.mentions))).all() == [[str(new)]]
    assert (await session.scalars(select(TicketNote.mentions))).all() == [[str(new)]]


class _Queue:
    def __init__(self) -> None:
        self.messages: list[MailMessage] = []

    async def enqueue(self, msg: MailMessage) -> None:
        self.messages.append(msg)


async def test_the_mention_mail_reaches_the_new_mentions_only(session: AsyncSession) -> None:
    w = await _seed(session)
    comment = Comment(
        application_id=w.app,
        author=w.subs["reader"],
        author_kind="principal",
        body="Bitte prüfen",
        visibility="internal",
        mentions=[str(w.ids[k]) for k in ("vote", "meet", "reader")],
    )
    session.add(comment)
    session.add(NotificationPreference(principal_id=w.ids["meet"], kind="mention", enabled=False))
    await session.commit()
    queue = _Queue()
    settings = load_settings()
    sent = await send_comment_mentions(
        session,
        queue=queue,  # type: ignore[arg-type]
        settings=settings,
        comment_id=comment.id,
        # "other" is no longer mentioned, the author is the actor, "meet" opted out.
        recipients=[w.ids[k] for k in ("vote", "meet", "reader", "other")],
        actor_sub=w.subs["reader"],
    )
    assert sent == 1
    (msg,) = queue.messages
    assert msg.to == (f"{w.subs['vote']}@example.org",)
    assert msg.subject == "Rita Reader hat Sie erwähnt: Antrag"
    assert "„Antrag“ erwähnt:\n\nBitte prüfen" in msg.text
    assert f"/applications/{w.app}#comment-{comment.id}" in msg.text
    assert msg.html is not None and "Bitte prüfen" in msg.html and "RR" in msg.html
    assert "weil Sie erwähnt wurden" in msg.html
    assert msg.idempotency_key == compute_idempotency_key(
        "comment_mentioned", str(comment.id), str(w.ids["vote"])
    )
    assert (
        await send_comment_mentions(
            session,
            queue=queue,  # type: ignore[arg-type]
            settings=settings,
            comment_id=uuid.uuid4(),
            recipients=[w.ids["vote"]],
            actor_sub=w.subs["reader"],
        )
        == 0
    )


async def test_the_ticket_mention_mail_links_the_note(session: AsyncSession) -> None:
    w = await _seed(session)
    ticket = Ticket(kind="bug", title="Knopf", body="b", reporter_email="r@example.org")
    session.add(ticket)
    await session.flush()
    note = TicketNote(
        ticket_id=ticket.id,
        author_id=w.ids["reader"],
        body="",
        mentions=[str(w.ids["vote"]), str(w.ids["reader"])],
    )
    session.add(note)
    await session.commit()
    queue = _Queue()
    sent = await send_ticket_mentions(
        session,
        queue=queue,  # type: ignore[arg-type]
        settings=load_settings(),
        note_id=note.id,
        recipients=[w.ids["vote"], w.ids["reader"]],
    )
    assert sent == 1
    (msg,) = queue.messages
    assert msg.subject.startswith("Rita Reader hat Sie erwähnt: T-")
    assert f"/tickets/{ticket.id}#note-{note.id}" in msg.text
    assert msg.idempotency_key == compute_idempotency_key(
        "ticket_mentioned", str(note.id), str(w.ids["vote"])
    )


async def test_the_mention_mails_skip_what_they_cannot_send(session: AsyncSession) -> None:
    w = await _seed(session)
    settings = load_settings()
    queue = _Queue()
    # An applicant comment that a manager edited: the bubble names the applicant.
    comment = Comment(
        application_id=w.app,
        author=None,
        author_kind="applicant",
        body="Frage",
        visibility="public",
        mentions=[str(w.ids["vote"])],
    )
    ticket = Ticket(kind="bug", title="Knopf", body="b", reporter_email="r@example.org")
    session.add_all([comment, ticket])
    await session.flush()
    gone = TicketNote(
        ticket_id=ticket.id,
        author_id=w.ids["reader"],
        body="x",
        mentions=[str(w.ids["vote"])],
        deleted_at=datetime.now(UTC),
    )
    lonely = TicketNote(
        ticket_id=ticket.id, author_id=w.ids["reader"], body="x", mentions=[str(w.ids["reader"])]
    )
    session.add_all([gone, lonely])
    await session.commit()
    assert (
        await send_comment_mentions(
            session,
            queue=queue,  # type: ignore[arg-type]
            settings=settings,
            comment_id=comment.id,
            recipients=[w.ids["vote"]],
            actor_sub="unknown-sub",
        )
        == 1
    )
    assert "Antragsteller:in" in (queue.messages[0].html or "")
    for note_id, ids in (
        (gone.id, [w.ids["vote"]]),
        (lonely.id, [w.ids["reader"]]),
        (lonely.id, []),
        (uuid.uuid4(), [w.ids["vote"]]),
    ):
        assert (
            await send_ticket_mentions(
                session,
                queue=queue,  # type: ignore[arg-type]
                settings=settings,
                note_id=note_id,
                recipients=ids,
            )
            == 0
        )
    assert (
        await send_comment_mentions(
            session,
            queue=queue,  # type: ignore[arg-type]
            settings=settings,
            comment_id=comment.id,
            recipients=[w.ids["other"]],
            actor_sub=w.subs["reader"],
        )
        == 0
    )


async def test_a_guest_application_and_a_lost_creator_add_no_creator(
    session: AsyncSession,
) -> None:
    w = await _seed(session)
    base = {w.ids["reader"], w.ids["read_all"]}
    app = await session.get(Application, w.plain_app)
    assert app is not None
    app.created_by = None
    await session.commit()
    assert {p.principal_id for p in await mentionable_people(session, w.plain_app)} == base
    app.created_by = "sub-without-a-row"
    await session.commit()
    assert {p.principal_id for p in await mentionable_people(session, w.plain_app)} == base


async def test_an_edit_keeps_a_mention_of_a_person_who_lost_the_access(
    session: AsyncSession,
) -> None:
    w = await _seed(session)
    svc = ApplicationsService(session)
    old = Comment(
        application_id=w.app,
        author=w.subs["reader"],
        author_kind="principal",
        body="@Otto",
        visibility="internal",
        mentions=[str(w.ids["other"])],
    )
    session.add(old)
    await session.commit()

    kept = await _edit(svc, w, old.id, [w.ids["other"], w.ids["vote"]])
    assert [m.principal_id for m in kept.mentions] == [w.ids["other"], w.ids["vote"]]
    assert list(svc.added_mentions) == [w.ids["vote"]]
    # Only a new mention must be mentionable now.
    with pytest.raises(ValidationProblem):
        await _edit(svc, w, old.id, [w.ids["other"], w.ids["plain"]])
