"""The activity page: the events of the items of a person (specs 001270-001277).

The page adds no event table (spec 001270). Each source reads a history that its module
already keeps:

- Anträge: ``status_event``, ``comment`` and ``submission_version`` (from version 2).
- To-do cards: ``todo_event`` and ``todo_comment``.
- Tickets: ``ticket_event`` and ``ticket_note``.
- Meetings: the ``audit_entry`` rows ``meeting_update`` of the meeting and
  ``protocol_finalize``, ``protocol_approval`` and ``protocol_reopen`` of its protocol,
  because a meeting keeps no history of its own.

Each source limits its rows in SQL to the items of the person (spec 001271). The service
then asks the read rule of the module for each item on the page, with the same scope as
the module route (spec 001272): ``resolve_app_read`` for an Antrag, ``BoardAccess.can_read``
for a card, ``ticket.manage`` or the own report for a ticket and
``MeetingRules.assert_can_read`` for a meeting. A row that the detail page of the item
does not show to the reader is left out too: an internal comment for a reader in the
applicant view, a team note or a non-status event of a ticket for its reporter.

The rows of all sources merge newest first. The cursor is the time and the key of the last
row (spec 001276), so a new event between two steps neither shifts nor repeats a row. A
source that returns a full batch may hold older rows than the oldest row it returned, so a
step only trusts the merged rows down to the oldest row of the fullest source and asks
again from there.
"""

from __future__ import annotations

import base64
import binascii
import uuid
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final, cast

from sqlalchemy import (
    ColumnElement,
    Select,
    Text,
    and_,
    collate,
    func,
    literal,
    or_,
    select,
)
from sqlalchemy import (
    cast as sql_cast,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.modules.activity.models import ActivityVisit
from app.modules.activity.schemas import (
    ActivityActor,
    ActivityEntry,
    ActivityPage,
    ChangeKind,
    ItemKind,
)
from app.modules.applications.access import resolve_app_read
from app.modules.applications.models import (
    Application,
    ApplicationObserver,
    Comment,
    StatusEvent,
    SubmissionVersion,
)
from app.modules.audit.actions import AuditAction
from app.modules.audit.models import AuditEntry
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.flow.models import State
from app.modules.meetings.models import Meeting, MeetingAttendance
from app.modules.meetings.rules import MeetingRules
from app.modules.site_config.features import Feature, active_features
from app.modules.tickets.access import TICKET_MANAGE
from app.modules.tickets.models import Ticket, TicketEvent, TicketNote
from app.modules.tickets.service import format_number
from app.modules.todos.access import BoardAccess, member_gremium_ids, token_reads
from app.modules.todos.links import card_url
from app.modules.todos.models import TodoAssignee, TodoBoard, TodoCard, TodoComment, TodoEvent
from app.shared.errors import ForbiddenError, NotFoundError, ValidationProblem
from app.shared.i18n import resolve_i18n

if TYPE_CHECKING:
    from app.modules.auth.principal import Principal

#: Rows per step of the page (spec 001276).
PAGE_SIZE: Final = 50

#: The steps one request may take to fill a page. A page whose items the reader mostly
#: cannot read any more stops here and hands out the cursor, so one request stays bounded.
MAX_ROUNDS: Final = 8

#: The longest detail text. A comment shows its first line only (spec 001277).
DETAIL_LENGTH: Final = 140

#: The kinds of item in the order of the filter chips (spec 001274).
ITEM_KINDS: Final[tuple[ItemKind, ...]] = ("application", "todo", "ticket", "meeting")

#: The feature a kind of item needs. An Antrag needs none.
KIND_FEATURE: Final[Mapping[ItemKind, Feature]] = {
    "todo": Feature.TODOS,
    "ticket": Feature.TICKETS,
    "meeting": Feature.MEETINGS,
}

#: The ``change`` of each ``todo_event.kind``. ``assigned`` splits by ``payload.added``.
TODO_CHANGES: Final[Mapping[str, ChangeKind]] = {
    "created": "todo.created",
    "moved": "todo.moved",
    "due": "todo.due",
    "linked": "todo.linked",
    "unlinked": "todo.unlinked",
    "checklist": "todo.checklist",
    "renamed": "todo.renamed",
    "archived": "todo.archived",
    "restored": "todo.restored",
}

#: The ``change`` of each ``ticket_event.kind``.
TICKET_CHANGES: Final[Mapping[str, ChangeKind]] = {
    "created": "ticket.created",
    "status": "ticket.status",
    "assignee": "ticket.assignee",
    "kind": "ticket.kind",
    "todo_done": "ticket.todo_done",
}

#: The ``change`` of each protocol action of the audit log.
PROTOCOL_CHANGES: Final[Mapping[str, ChangeKind]] = {
    AuditAction.PROTOCOL_FINALIZE.value: "protocol.finalized",
    AuditAction.PROTOCOL_APPROVAL.value: "protocol.approved",
    AuditAction.PROTOCOL_REOPEN.value: "protocol.reopened",
}


@dataclass(frozen=True, slots=True)
class Cursor:
    """The position after the last row of a step: its time and its key."""

    at: datetime
    key: str

    def encode(self) -> str:
        """Encode the cursor as an opaque URL-safe string."""
        raw = f"{self.at.isoformat()}|{self.key}".encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    @classmethod
    def decode(cls, value: str) -> Cursor:
        """Decode a cursor of `encode`.

        Raises:
            ValidationProblem: The value is not a cursor of this page (``invalid_cursor``).
        """
        try:
            raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode()
            at, key = raw.split("|", 1)
            parsed = datetime.fromisoformat(at)
        except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
            raise _bad_cursor() from exc
        if parsed.tzinfo is None or not key:
            raise _bad_cursor()
        return cls(parsed, key)


def _bad_cursor() -> ValidationProblem:
    """The problem of a cursor that this page did not hand out."""
    msg = "The cursor is not valid."
    return ValidationProblem(msg, code="invalid_cursor", errors=[{"field": "cursor", "msg": msg}])


@dataclass(frozen=True, slots=True)
class Me:
    """The reader: the principal, its row id, its e-mail, the language and its Gremien.

    ``lang`` is the language of the texts that the server resolves (a state label).
    ``gremien`` holds the Gremien where the reader is an active member (spec 001271).
    """

    principal: Principal
    id: uuid.UUID | None
    email: str | None
    lang: str = "de"
    gremien: frozenset[uuid.UUID] = frozenset()

    @property
    def sub(self) -> str:
        """The OIDC ``sub`` of the reader."""
        return self.principal.sub


@dataclass(frozen=True, slots=True)
class Raw:
    """One event as a source reads it, before the gate and the names.

    Attributes:
        visibility: ``internal`` or ``public`` for a comment or a note, else ``None``.
        reporter_reads: The reporter of a ticket reads this event (status and public
            notes only).
        applicant_author: The comment comes from the applicant without an account.
    """

    at: datetime
    key: str
    kind: ItemKind
    item_id: uuid.UUID
    change: ChangeKind
    detail: str | None = None
    status: str | None = None
    actor_sub: str | None = None
    actor_id: uuid.UUID | None = None
    visibility: str | None = None
    reporter_reads: bool = True
    applicant_author: bool = False

    @property
    def cursor(self) -> Cursor:
        """The cursor right after this row."""
        return Cursor(self.at, self.key)


@dataclass(frozen=True, slots=True)
class Gate:
    """What the reader may see of one item.

    Attributes:
        internal: The reader sees internal comments and notes.
        applicant_view: The reader reads an Antrag as its applicant, so a member shows
            as the Gremium (``committee``), never by name.
        reporter: The reader reads a ticket only as its reporter.
    """

    title: str | None
    url: str
    internal: bool = True
    applicant_view: bool = False
    reporter: bool = False


#: A column or a mapped attribute of a source query.
type Col = ColumnElement[Any] | InstrumentedAttribute[Any]

#: One source: the reader, the cursor, the batch size and whether own rows count.
type Source = Callable[[Me, Cursor | None, int, bool], Awaitable[list[Raw]]]

#: The read rule of one kind: the reader and the item ids give the readable items.
type GateCheck = Callable[[Me, set[uuid.UUID]], Awaitable[dict[uuid.UUID, Gate]]]


#: The gates already asked in one request, per kind and item. ``None`` is unreadable.
type Gates = dict[tuple[ItemKind, uuid.UUID], Gate | None]


def first_line(text: str | None) -> str | None:
    """Return the first non-empty line of a text, cut to `DETAIL_LENGTH` characters."""
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped:
            if len(stripped) > DETAIL_LENGTH:
                return stripped[: DETAIL_LENGTH - 1].rstrip() + "…"
            return stripped
    return None


def _key(prefix: str, id_col: Col) -> ColumnElement[str]:
    """The key of a row: the source prefix and the id, compared byte by byte.

    The collation ``C`` makes Postgres compare the key the way Python compares the
    string, so the cursor condition and the merge agree.
    """
    return collate(func.concat(literal(prefix), sql_cast(id_col, Text)), "C")


def _after(
    at_col: Col, key: ColumnElement[str], cursor: Cursor | None
) -> ColumnElement[bool] | None:
    """The condition "older than the cursor", or ``None`` for the first step."""
    if cursor is None:
        return None
    return or_(at_col < cursor.at, and_(at_col == cursor.at, key < cursor.key))


def _page[*Ts](
    stmt: Select[*Ts],
    at_col: Col,
    key: ColumnElement[str],
    cursor: Cursor | None,
    limit: int,
) -> Select[*Ts]:
    """Add the cursor, the order newest first and the batch size to a source query."""
    after = _after(at_col, key, cursor)
    if after is not None:
        stmt = stmt.where(after)
    return stmt.order_by(at_col.desc(), key.desc()).limit(limit)


def _not_by(col: Col, value: object, own: bool) -> ColumnElement[bool] | None:
    """The condition "not by the reader" unless own rows count (spec 001273)."""
    if own or value is None:
        return None
    return or_(col.is_(None), col != value)


def _where[*Ts](stmt: Select[*Ts], *conds: ColumnElement[bool] | None) -> Select[*Ts]:
    """Add the conditions that are not ``None``."""
    real = [c for c in conds if c is not None]
    return stmt.where(*real) if real else stmt


class ActivityService:
    """The events of the items of the reader, behind the read rule of each module."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the service to a session."""
        self.session = session

    # ------------------------------------------------------------------ the page

    async def page(
        self,
        principal: Principal,
        *,
        kinds: Iterable[ItemKind] = ITEM_KINDS,
        own: bool = False,
        cursor: str | None = None,
        lang: str = "de",
        limit: int = PAGE_SIZE,
    ) -> ActivityPage:
        """Read one step of the page, newest first.

        `kinds` limits the page to these kinds of item; an empty selection means all
        (spec 001274). `own` shows the events of the reader too (spec 001273). The
        sources of a feature that is off are not asked.
        """
        me = await self._me(principal, lang)
        read_at = datetime.now(UTC)
        seen_at = await self._seen_at(me)
        entries, next_cursor = await self._collect(
            me, self._sources(await self._kinds(kinds)), own=own, cursor=cursor, limit=limit
        )
        return ActivityPage(
            entries=[
                e.model_copy(update={"is_new": seen_at is not None and e.at > seen_at})
                for e in entries
            ],
            nextCursor=next_cursor,
            seenAt=seen_at,
            readAt=read_at,
        )

    async def has_new(self, principal: Principal) -> bool:
        """Tell whether an event of another person waits after the last visit.

        Without a visit every event counts, so the dot leads a person to the page once.
        """
        me = await self._me(principal)
        seen_at = await self._seen_at(me)
        entries, _ = await self._collect(
            me, self._sources(await self._kinds(ITEM_KINDS)), own=False, cursor=None, limit=1
        )
        return bool(entries) and (seen_at is None or entries[0].at > seen_at)

    async def mark_seen(self, principal: Principal, at: datetime) -> None:
        """Store the time up to which the reader has seen the page (spec 001275).

        The mark never moves back and never past now, so a late or a forged request
        cannot hide events that have not happened yet. The caller commits (000474).
        """
        me = await self._me(principal)
        if me.id is None:
            return
        insert_row = insert(ActivityVisit).values(principal_id=me.id, seen_at=_mark(at))
        await self.session.execute(
            insert_row.on_conflict_do_update(
                index_elements=[ActivityVisit.principal_id],
                set_={"seen_at": func.greatest(ActivityVisit.seen_at, insert_row.excluded.seen_at)},
            )
        )

    # ------------------------------------------------------------------ the merge

    async def _collect(
        self,
        me: Me,
        sources: Sequence[tuple[ItemKind, Source]],
        *,
        own: bool,
        cursor: str | None,
        limit: int,
    ) -> tuple[list[ActivityEntry], str | None]:
        """Merge the sources newest first and keep the rows the reader may see."""
        return await self._step(
            me,
            sources,
            own=own,
            pos=Cursor.decode(cursor) if cursor else None,
            limit=limit,
            gates={},
            kept=(),
            rounds=MAX_ROUNDS,
        )

    async def _step(
        self,
        me: Me,
        sources: Sequence[tuple[ItemKind, Source]],
        *,
        own: bool,
        pos: Cursor | None,
        limit: int,
        gates: Gates,
        kept: tuple[tuple[Raw, Gate], ...],
        rounds: int,
    ) -> tuple[list[ActivityEntry], str | None]:
        """Run one round of the merge.

        Read a batch of each source after `pos`, keep the readable rows, and go on from
        the last trusted row while the page is not full.

        A round that ends without a full page and without a last round hands out the
        cursor of its last trusted row, so one request stays bounded.
        """
        batch = limit + 1
        answers = [await run(me, pos, batch, own) for _, run in sources]
        rows = sorted(
            (row for found in answers for row in found),
            key=lambda r: (r.at, r.key),
            reverse=True,
        )
        if not rows:
            return await self._entries(me, kept[:limit]), None
        full = [found[-1] for found in answers if len(found) == batch]
        floor = max((r.at, r.key) for r in full) if full else None
        trusted = [r for r in rows if floor is None or (r.at, r.key) >= floor]
        await self._ask_gates(me, trusted, gates)
        found_rows = (*kept, *_readable(trusted, gates))
        if len(found_rows) > limit:
            return (
                await self._entries(me, found_rows[:limit]),
                found_rows[limit - 1][0].cursor.encode(),
            )
        if floor is None:
            return await self._entries(me, found_rows), None
        if rounds <= 1:
            return await self._entries(me, found_rows), trusted[-1].cursor.encode()
        return await self._step(
            me,
            sources,
            own=own,
            pos=trusted[-1].cursor,
            limit=limit,
            gates=gates,
            kept=found_rows,
            rounds=rounds - 1,
        )

    async def _ask_gates(self, me: Me, rows: Sequence[Raw], gates: Gates) -> None:
        """Ask the read rule of each module for the items not asked yet."""
        checks: Mapping[ItemKind, GateCheck] = {
            "application": self._gate_applications,
            "todo": self._gate_todos,
            "ticket": self._gate_tickets,
            "meeting": self._gate_meetings,
        }
        for kind, check in checks.items():
            ids = {r.item_id for r in rows if r.kind == kind and (kind, r.item_id) not in gates}
            if ids:
                found = await check(me, ids)
                gates.update({(kind, item_id): found.get(item_id) for item_id in ids})

    async def _entries(self, me: Me, rows: Sequence[tuple[Raw, Gate]]) -> list[ActivityEntry]:
        """Turn the kept rows into entries, with the names of the actors."""
        names = await self._names([r for r, _ in rows])
        return [
            ActivityEntry(
                id=row.key,
                at=row.at,
                itemKind=row.kind,
                itemId=str(row.item_id),
                itemTitle=gate.title,
                url=gate.url,
                change=row.change,
                detail=row.detail,
                status=row.status,
                actor=_actor(row, gate, names, own=_is_own(row, me)),
                own=_is_own(row, me),
            )
            for row, gate in rows
        ]

    # ------------------------------------------------------------------ the reader

    async def _me(self, principal: Principal, lang: str = "de") -> Me:
        """Load the row id, the e-mail and the Gremien of the reader."""
        row = (
            await self.session.execute(
                select(PrincipalRow.id, PrincipalRow.email).where(PrincipalRow.sub == principal.sub)
            )
        ).first()
        if row is None:
            return Me(principal, None, principal.email, lang)
        gremien = await member_gremium_ids(self.session, principal)
        return Me(principal, row.id, row.email or principal.email, lang, gremien)

    async def _seen_at(self, me: Me) -> datetime | None:
        """The last visit of the reader, or ``None``."""
        if me.id is None:
            return None
        return await self.session.scalar(
            select(ActivityVisit.seen_at).where(ActivityVisit.principal_id == me.id)
        )

    async def _kinds(self, kinds: Iterable[ItemKind]) -> list[ItemKind]:
        """The selected kinds whose feature is on. No selection means every kind."""
        wanted = set(kinds) or set(ITEM_KINDS)
        enabled = await active_features(self.session)
        return [
            k
            for k in ITEM_KINDS
            if k in wanted and (k not in KIND_FEATURE or KIND_FEATURE[k] in enabled)
        ]

    def _sources(self, kinds: Sequence[ItemKind]) -> list[tuple[ItemKind, Source]]:
        """The sources of the kinds."""
        table: Mapping[ItemKind, Sequence[Source]] = {
            "application": (
                self._application_status,
                self._application_comments,
                self._application_versions,
            ),
            "todo": (self._todo_events, self._todo_comments),
            "ticket": (self._ticket_events, self._ticket_notes),
            "meeting": (self._meeting_updates, self._protocol_events),
        }
        return [(kind, run) for kind in kinds for run in table[kind]]

    async def _names(self, rows: Sequence[Raw]) -> dict[str | uuid.UUID, str | None]:
        """The display names of the actors, by ``sub`` and by row id."""
        subs = {r.actor_sub for r in rows if r.actor_sub}
        ids = {r.actor_id for r in rows if r.actor_id}
        if not subs and not ids:
            return {}
        found = (
            await self.session.execute(
                select(PrincipalRow.id, PrincipalRow.sub, PrincipalRow.display_name).where(
                    or_(PrincipalRow.sub.in_(subs), PrincipalRow.id.in_(ids))
                )
            )
        ).all()
        return {key: r.display_name for r in found for key in (r.sub, r.id)}

    # ------------------------------------------------------------------ Anträge

    def _my_applications(self, me: Me) -> Select[uuid.UUID]:
        """The Anträge of the reader (spec 001271): own, captured, observed, commented."""
        mentioned = (
            (
                Application.id.in_(
                    select(Comment.application_id).where(Comment.mentions.contains([str(me.id)]))
                ),
            )
            if me.id is not None
            else ()
        )
        observed = (
            (
                Application.id.in_(
                    select(ApplicationObserver.application_id).where(
                        ApplicationObserver.email == me.email
                    )
                ),
            )
            if me.email
            else ()
        )
        return select(Application.id).where(
            or_(
                Application.created_by == me.sub,
                Application.captured_by == me.sub,
                Application.id.in_(select(Comment.application_id).where(Comment.author == me.sub)),
                *mentioned,
                *observed,
            )
        )

    async def _application_status(
        self, me: Me, cursor: Cursor | None, limit: int, own: bool
    ) -> list[Raw]:
        """The status timeline of the Anträge of the reader."""
        key = _key("status:", StatusEvent.id)
        stmt = _where(
            select(StatusEvent, State.label_i18n, key)
            .join(State, State.id == StatusEvent.to_state_id)
            .where(StatusEvent.application_id.in_(self._my_applications(me))),
            _not_by(StatusEvent.actor, me.sub, own),
        )
        rows = (
            (await self.session.execute(_page(stmt, StatusEvent.at, key, cursor, limit)))
            .tuples()
            .all()
        )
        return [
            Raw(
                at=ev.at,
                key=k,
                kind="application",
                item_id=ev.application_id,
                change="application.status",
                detail=resolve_i18n(label, me.lang, "de"),
                actor_sub=ev.actor,
            )
            for ev, label, k in rows
        ]

    async def _application_comments(
        self, me: Me, cursor: Cursor | None, limit: int, own: bool
    ) -> list[Raw]:
        """The comments on the Anträge of the reader."""
        key = _key("comment:", Comment.id)
        stmt = _where(
            select(Comment, key).where(Comment.application_id.in_(self._my_applications(me))),
            _not_by(Comment.author, me.sub, own),
        )
        rows = (
            (await self.session.execute(_page(stmt, Comment.at, key, cursor, limit))).tuples().all()
        )
        return [
            Raw(
                at=c.at,
                key=k,
                kind="application",
                item_id=c.application_id,
                change="comment",
                detail=first_line(c.body),
                actor_sub=c.author,
                visibility=c.visibility,
                applicant_author=c.author_kind == "applicant",
            )
            for c, k in rows
        ]

    async def _application_versions(
        self, me: Me, cursor: Cursor | None, limit: int, own: bool
    ) -> list[Raw]:
        """The data edits of the Anträge of the reader, without a value (spec 001277)."""
        key = _key("version:", SubmissionVersion.id)
        stmt = _where(
            select(
                SubmissionVersion.application_id,
                SubmissionVersion.at,
                SubmissionVersion.changed_by,
                key,
            ).where(
                SubmissionVersion.application_id.in_(self._my_applications(me)),
                SubmissionVersion.version > 1,
            ),
            _not_by(SubmissionVersion.changed_by, me.sub, own),
        )
        rows = (
            (await self.session.execute(_page(stmt, SubmissionVersion.at, key, cursor, limit)))
            .tuples()
            .all()
        )
        return [
            Raw(
                at=at,
                key=k,
                kind="application",
                item_id=app_id,
                change="application.edited",
                actor_sub=changed_by,
            )
            for app_id, at, changed_by, k in rows
        ]

    async def _gate_applications(self, me: Me, ids: set[uuid.UUID]) -> dict[uuid.UUID, Gate]:
        """Reuses `resolve_app_read` with the observers, like the detail route."""
        rows = (
            (
                await self.session.execute(
                    select(Application.id, Application.data).where(Application.id.in_(ids))
                )
            )
            .tuples()
            .all()
        )
        found = [(app_id, await self._application_gate(me, app_id, data)) for app_id, data in rows]
        return {app_id: gate for app_id, gate in found if gate is not None}

    async def _application_gate(
        self, me: Me, app_id: uuid.UUID, data: Mapping[str, Any] | None
    ) -> Gate | None:
        """The gate of one Antrag, or ``None`` when the reader cannot read it."""
        try:
            access = await resolve_app_read(
                self.session, app_id, me.principal, None, observers=True
            )
        except (ForbiddenError, NotFoundError):
            return None
        title = (data or {}).get("title")
        applicant_view = access.is_applicant_view
        return Gate(
            title=title.strip() if isinstance(title, str) and title.strip() else None,
            url=f"/my-applications/{app_id}" if applicant_view else f"/applications/{app_id}",
            internal=access.can_see_internal,
            applicant_view=applicant_view,
        )

    # ------------------------------------------------------------------ to-do cards

    def _my_cards(self, me: Me) -> Select[uuid.UUID]:
        """The cards of the reader (spec 001271): created, assigned, commented, mentioned."""
        return select(TodoCard.id).where(
            or_(
                TodoCard.created_by == me.id,
                TodoCard.id.in_(
                    select(TodoAssignee.card_id).where(TodoAssignee.principal_id == me.id)
                ),
                TodoCard.id.in_(
                    select(TodoComment.card_id).where(
                        TodoComment.deleted_at.is_(None),
                        or_(
                            TodoComment.author_id == me.id,
                            TodoComment.mentions.contains([str(me.id)]),
                        ),
                    )
                ),
            )
        )

    async def _todo_events(self, me: Me, cursor: Cursor | None, limit: int, own: bool) -> list[Raw]:
        """The timeline of the cards of the reader."""
        if me.id is None or not token_reads(me.principal):
            return []
        key = _key("todo_event:", TodoEvent.id)
        stmt = _where(
            select(TodoEvent, key).where(TodoEvent.card_id.in_(self._my_cards(me))),
            _not_by(TodoEvent.actor_id, me.id, own),
        )
        rows = (
            (await self.session.execute(_page(stmt, TodoEvent.created_at, key, cursor, limit)))
            .tuples()
            .all()
        )
        return [_todo_raw(ev, k) for ev, k in rows]

    async def _todo_comments(
        self, me: Me, cursor: Cursor | None, limit: int, own: bool
    ) -> list[Raw]:
        """The comments on the cards of the reader."""
        if me.id is None or not token_reads(me.principal):
            return []
        key = _key("todo_comment:", TodoComment.id)
        stmt = _where(
            select(TodoComment, key).where(
                TodoComment.card_id.in_(self._my_cards(me)), TodoComment.deleted_at.is_(None)
            ),
            _not_by(TodoComment.author_id, me.id, own),
        )
        rows = (
            (await self.session.execute(_page(stmt, TodoComment.created_at, key, cursor, limit)))
            .tuples()
            .all()
        )
        return [
            Raw(
                at=c.created_at,
                key=k,
                kind="todo",
                item_id=c.card_id,
                change="comment",
                detail=first_line(c.body),
                actor_id=c.author_id,
            )
            for c, k in rows
        ]

    async def _gate_todos(self, me: Me, ids: set[uuid.UUID]) -> dict[uuid.UUID, Gate]:
        """Reuses `BoardAccess.can_read` of the board that the card is on now."""
        rows = (
            await self.session.execute(
                select(TodoCard.id, TodoCard.title, TodoBoard)
                .join(TodoBoard, TodoBoard.id == TodoCard.board_id)
                .where(TodoCard.id.in_(ids))
            )
        ).all()
        access = BoardAccess(self.session)
        readable = [
            (card_id, title)
            for card_id, title, board in rows
            if await access.can_read(board, me.principal)
        ]
        return {card_id: Gate(title=title, url=card_url(card_id)) for card_id, title in readable}

    # ------------------------------------------------------------------ tickets

    def _my_tickets(self, me: Me) -> Select[uuid.UUID]:
        """The tickets of the reader (spec 001271): reported, assigned, noted, mentioned."""
        return select(Ticket.id).where(
            or_(
                Ticket.reporter_principal_id == me.id,
                Ticket.assignee_id == me.id,
                Ticket.id.in_(
                    select(TicketNote.ticket_id).where(
                        TicketNote.deleted_at.is_(None),
                        or_(
                            TicketNote.author_id == me.id,
                            TicketNote.mentions.contains([str(me.id)]),
                        ),
                    )
                ),
            )
        )

    async def _ticket_events(
        self, me: Me, cursor: Cursor | None, limit: int, own: bool
    ) -> list[Raw]:
        """The timeline of the tickets of the reader."""
        if me.id is None:
            return []
        key = _key("ticket_event:", TicketEvent.id)
        stmt = _where(
            select(TicketEvent, key).where(TicketEvent.ticket_id.in_(self._my_tickets(me))),
            _not_by(TicketEvent.actor_id, me.id, own),
        )
        rows = (
            (await self.session.execute(_page(stmt, TicketEvent.created_at, key, cursor, limit)))
            .tuples()
            .all()
        )
        return [_ticket_raw(ev, k) for ev, k in rows]

    async def _ticket_notes(
        self, me: Me, cursor: Cursor | None, limit: int, own: bool
    ) -> list[Raw]:
        """The notes on the tickets of the reader."""
        if me.id is None:
            return []
        key = _key("ticket_note:", TicketNote.id)
        stmt = _where(
            select(TicketNote, key).where(
                TicketNote.ticket_id.in_(self._my_tickets(me)), TicketNote.deleted_at.is_(None)
            ),
            _not_by(TicketNote.author_id, me.id, own),
        )
        rows = (
            (await self.session.execute(_page(stmt, TicketNote.created_at, key, cursor, limit)))
            .tuples()
            .all()
        )
        return [
            Raw(
                at=n.created_at,
                key=k,
                kind="ticket",
                item_id=n.ticket_id,
                change="comment",
                detail=first_line(n.body),
                actor_id=n.author_id,
                visibility=n.visibility,
            )
            for n, k in rows
        ]

    async def _gate_tickets(self, me: Me, ids: set[uuid.UUID]) -> dict[uuid.UUID, Gate]:
        """Reuses the ticket gate: ``ticket.manage`` reads all, a reporter the own report."""
        manage = me.principal.has(TICKET_MANAGE)
        rows = (
            await self.session.execute(
                select(Ticket.id, Ticket.number, Ticket.title, Ticket.reporter_principal_id).where(
                    Ticket.id.in_(ids)
                )
            )
        ).all()
        return {
            ticket_id: Gate(
                title=f"{format_number(number)} · {title}",
                url=f"/tickets/{ticket_id}",
                internal=manage,
                reporter=not manage,
            )
            for ticket_id, number, title, reporter in rows
            if manage or (me.id is not None and reporter == me.id)
        }

    # ------------------------------------------------------------------ meetings

    def _my_meetings(self, me: Me) -> Select[str]:
        """The meetings of the reader as text ids (spec 001271).

        A meeting of a Gremium of the reader, or one the reader created, keeps the minutes
        of or attended.
        """
        held = (
            (
                Meeting.protokollant_id == me.id,
                Meeting.id.in_(
                    select(MeetingAttendance.meeting_id).where(
                        MeetingAttendance.principal_id == me.id
                    )
                ),
            )
            if me.id is not None
            else ()
        )
        of_gremien = (Meeting.gremium_id.in_(me.gremien),) if me.gremien else ()
        return select(sql_cast(Meeting.id, Text)).where(
            or_(Meeting.created_by == me.sub, *held, *of_gremien)
        )

    async def _meeting_updates(
        self, me: Me, cursor: Cursor | None, limit: int, own: bool
    ) -> list[Raw]:
        """The status and date changes of the meetings of the reader, from the audit log."""
        key = _key("audit:", AuditEntry.id)
        stmt = _where(
            select(AuditEntry, key).where(
                AuditEntry.action == AuditAction.MEETING_UPDATE.value,
                AuditEntry.target_type == "meeting",
                AuditEntry.target_id.in_(self._my_meetings(me)),
            ),
            _not_by(AuditEntry.actor, me.sub, own),
        )
        rows = (
            (await self.session.execute(_page(stmt, AuditEntry.at, key, cursor, limit)))
            .tuples()
            .all()
        )
        return [raw for entry, k in rows if (raw := _meeting_raw(entry, k)) is not None]

    async def _protocol_events(
        self, me: Me, cursor: Cursor | None, limit: int, own: bool
    ) -> list[Raw]:
        """The protocol steps of the meetings of the reader, from the audit log."""
        key = _key("audit:", AuditEntry.id)
        stmt = _where(
            select(AuditEntry, key).where(
                AuditEntry.action.in_(list(PROTOCOL_CHANGES)),
                AuditEntry.target_type == "protocol",
                AuditEntry.data["meetingId"].astext.in_(self._my_meetings(me)),
            ),
            _not_by(AuditEntry.actor, me.sub, own),
        )
        rows = (
            (await self.session.execute(_page(stmt, AuditEntry.at, key, cursor, limit)))
            .tuples()
            .all()
        )
        return [raw for entry, k in rows if (raw := _protocol_raw(entry, k)) is not None]

    async def _gate_meetings(self, me: Me, ids: set[uuid.UUID]) -> dict[uuid.UUID, Gate]:
        """Reuses `MeetingRules.assert_can_read`, the gate of the meeting detail."""
        rows = (
            (
                await self.session.execute(
                    select(Meeting.id, Meeting.title).where(Meeting.id.in_(ids))
                )
            )
            .tuples()
            .all()
        )
        rules = MeetingRules(self.session)
        readable = [
            (meeting_id, title)
            for meeting_id, title in rows
            if await _can_read_meeting(rules, meeting_id, me.principal)
        ]
        return {
            meeting_id: Gate(title=title, url=f"/meetings/{meeting_id}")
            for meeting_id, title in readable
        }


#: The payload key that names the detail of a card event: the column of a move, the new
#: title of a rename, the text of a checklist item.
TODO_DETAIL: Final[Mapping[str, str]] = {
    "moved": "toColumnName",
    "renamed": "to",
    "checklist": "text",
}


def _todo_raw(ev: TodoEvent, key: str) -> Raw:
    """One card event as a row. A move names the target column, a rename the new title."""
    payload: Mapping[str, Any] = ev.payload or {}
    assigned: ChangeKind = "todo.assigned" if payload.get("added", True) else "todo.unassigned"
    detail = payload.get(TODO_DETAIL.get(ev.kind, ""))
    return Raw(
        at=ev.created_at,
        key=key,
        kind="todo",
        item_id=ev.card_id,
        change=assigned if ev.kind == "assigned" else TODO_CHANGES.get(ev.kind, "todo.created"),
        detail=first_line(detail) if isinstance(detail, str) else None,
        actor_id=ev.actor_id,
    )


def _meeting_raw(entry: AuditEntry, key: str) -> Raw | None:
    """One ``meeting_update`` entry as a row: a status change, or another change."""
    item = _uuid(entry.target_id)
    if item is None:
        return None
    status = _status_to(entry.data)
    return Raw(
        at=entry.at,
        key=key,
        kind="meeting",
        item_id=item,
        change="meeting.status" if status is not None else "meeting.updated",
        status=status,
        actor_sub=entry.actor,
    )


def _protocol_raw(entry: AuditEntry, key: str) -> Raw | None:
    """One protocol entry of the audit log as a row of its meeting."""
    item = _uuid((entry.data or {}).get("meetingId"))
    if item is None:
        return None
    return Raw(
        at=entry.at,
        key=key,
        kind="meeting",
        item_id=item,
        change=PROTOCOL_CHANGES[entry.action],
        actor_sub=entry.actor,
    )


async def _can_read_meeting(
    rules: MeetingRules, meeting_id: uuid.UUID, principal: Principal
) -> bool:
    """Tell whether `MeetingRules.assert_can_read` lets the principal read the meeting."""
    try:
        await rules.assert_can_read(meeting_id, principal)
    except (ForbiddenError, NotFoundError):
        return False
    return True


def _mark(at: datetime) -> datetime:
    """The visit mark of a time: aware, and never past now."""
    aware = at if at.tzinfo is not None else at.replace(tzinfo=UTC)
    return min(aware, datetime.now(UTC))


def _readable(rows: Sequence[Raw], gates: Gates) -> tuple[tuple[Raw, Gate], ...]:
    """The rows whose item the reader reads and whose detail page shows them."""
    return tuple(
        (row, gate)
        for row in rows
        for gate in (gates.get((row.kind, row.item_id)),)
        if gate is not None and _shows(row, gate)
    )


def _ticket_raw(ev: TicketEvent, key: str) -> Raw:
    """One ticket event as a row. A status change carries the new status key."""
    payload: Mapping[str, Any] = ev.payload or {}
    to = payload.get("to")
    return Raw(
        at=ev.created_at,
        key=key,
        kind="ticket",
        item_id=ev.ticket_id,
        change=TICKET_CHANGES.get(ev.kind, "ticket.created"),
        status=to if ev.kind == "status" and isinstance(to, str) else None,
        actor_id=ev.actor_id,
        reporter_reads=ev.kind == "status",
    )


def _status_to(data: Mapping[str, Any] | None) -> str | None:
    """The new status of a ``meeting_update`` entry, or ``None`` for another change."""
    changes = (data or {}).get("changes")
    if not isinstance(changes, dict):
        return None
    status = cast(dict[str, Any], changes).get("status")
    if not isinstance(status, dict):
        return None
    to = cast(dict[str, Any], status).get("to")
    return to if isinstance(to, str) else None


def _uuid(value: object) -> uuid.UUID | None:
    """Parse an id of the audit log, or ``None``."""
    if not isinstance(value, str):
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _shows(row: Raw, gate: Gate) -> bool:
    """Tell whether the detail page of the item shows this row to the reader (001272)."""
    if row.visibility == "internal" and not gate.internal:
        return False
    return not (gate.reporter and not row.reporter_reads)


def _is_own(row: Raw, me: Me) -> bool:
    """Tell whether the reader made the change."""
    if row.actor_id is not None:
        return row.actor_id == me.id
    return row.actor_sub is not None and row.actor_sub == me.sub


def _actor(
    row: Raw, gate: Gate, names: Mapping[str | uuid.UUID, str | None], *, own: bool
) -> ActivityActor:
    """The actor of a row as the detail page of the item names it.

    In the applicant view a member shows as the Gremium, never by name.
    """
    if row.applicant_author:
        return ActivityActor(kind="applicant")
    ref: str | uuid.UUID | None = row.actor_id or row.actor_sub
    if ref is None or (isinstance(ref, str) and ref.startswith("system")):
        return ActivityActor(kind="system")
    if ref == "applicant":
        return ActivityActor(kind="applicant")
    if gate.applicant_view and not own:
        return ActivityActor(kind="committee")
    return ActivityActor(kind="person", name=names.get(ref))
