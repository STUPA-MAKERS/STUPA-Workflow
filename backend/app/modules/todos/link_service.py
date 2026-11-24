"""Links between any two elements: list, add, remove, search and the read sheet.

The routes of ``/api/links`` (spec 001409) use this service. A link has no direction
(spec 001401): it shows in ``Verknüpft`` of both ends. The rules:

* Any two elements of the kinds of ``LINK_KINDS`` link, also two of one kind, never an
  element to itself, at most once per pair (spec 001400).
* A person adds or removes a link when the person reads both ends by the rule of their
  kind and may change at least one of them (spec 001404, ``LinkRights``).
* Only a card gives read access to its links (specs 000487, 001405): the links of a
  card resolve with ``grants``, the links of any other element without.
* A link with a Paperless document needs ``paperless.use`` and the change right of the
  other element. Two Paperless documents do not link. A new link stores the title, the
  type and the date of the document (§F/integrations/paperless/002763-002765).
* A link with a card end writes the card events ``linked`` and ``unlinked`` and touches
  the board, and an Event keeps its Antrag, Buchung or invoice to itself
  (``event_link_taken``).
* Each added or removed link writes an audit entry with the grant of a token
  (§F/collaboration/links/002923, ``link_audit``).

The list shows a linked Event first, then the other links in the order of the kinds of
``LINK_KINDS``, and in each kind the newest link first (spec 001407).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.actions import AuditAction
from app.modules.auth.principal import Principal
from app.modules.todos import link_store
from app.modules.todos.link_audit import audit_link
from app.modules.todos.link_rights import LinkRights
from app.modules.todos.link_store import Edge
from app.modules.todos.link_view import LinkViewer
from app.modules.todos.links import HIDDEN, Resolved, link_kinds_on
from app.modules.todos.models import LINK_KINDS, Link, LinkEnd, TodoBoard, TodoCard
from app.modules.todos.schemas import (
    LinkRow,
    LinksOut,
    TodoLinkedCard,
    TodoLinkTarget,
    TodoLinkView,
)
from app.modules.todos.service import TodoService
from app.shared.errors import ConflictError, ForbiddenError, NotFoundError, ValidationProblem

#: The kind that gives read access to its links (spec 001405).
GRANTING_KIND = "todo"
#: The kind of a Paperless document (§F/integrations/paperless/002763).
PAPERLESS_KIND = "paperless"


def _invalid(msg: str, code: str, field_name: str) -> ValidationProblem:
    return ValidationProblem(msg, code=code, errors=[{"field": field_name, "msg": msg}])


def _order(row: LinkRow) -> tuple[bool, int, float]:
    """A linked Event first, then by kind, then the newest first."""
    return (
        row.card is None or row.card.event is None,
        LINK_KINDS.index(row.kind),
        -row.created_at.timestamp(),
    )


@dataclass(frozen=True, slots=True)
class LinkService:
    """The links of the elements, as one principal sees and changes them.

    Attributes:
        session: The database session.
        todos: The to-do service; it gives the cards and the read rules.
        rights: The check whether the principal changes an element.
    """

    session: AsyncSession
    todos: TodoService
    rights: LinkRights

    @classmethod
    def on(cls, session: AsyncSession, todos: TodoService | None = None) -> LinkService:
        """Build the service on a session, with the given to-do service or a new one."""
        cards = todos or TodoService(session)
        return cls(session, cards, LinkRights(session, cards.access))

    @property
    def paperless_down(self) -> bool:
        """Tell if Paperless did not answer the newest search over all kinds (002766)."""
        return self.todos.links.paperless_down

    async def _reads(self, end: LinkEnd, principal: Principal) -> bool:
        """Tell if the principal reads the element by the rule of its kind."""
        return await self.todos.links.readable(end[0], end[1], principal)

    async def _changes(self, end: LinkEnd, principal: Principal) -> bool:
        return await self.rights.can_change(end[0], end[1], principal)

    async def of(self, kind: str, target_id: uuid.UUID, principal: Principal) -> LinksOut:
        """The links of an element that the principal reads.

        Raises:
            NotFoundError: The principal does not read the element (HTTP 404).
        """
        own: LinkEnd = (kind, target_id)
        if not await self._reads(own, principal):
            raise NotFoundError(f"{kind} {target_id} not found")
        found = await link_store.edges(
            self.session, kind, [target_id], await link_kinds_on(self.session)
        )
        resolved = await self.todos.links.resolve(
            {edge.target for edge in found}, principal, grants=kind == GRANTING_KIND
        )
        cards = await self.todos.linked_cards(
            [e.target_id for e in found if e.kind == "todo"], principal
        )
        can_link = LinkRights.may_touch(kind, principal) and await self._changes(own, principal)
        rows = [
            await self._row(edge, resolved.get(edge.target, HIDDEN), cards, can_link, principal)
            for edge in found
        ]
        visible = [row for row in rows if row.kind != "todo" or row.card is not None]
        return LinksOut(can_link=can_link, links=sorted(visible, key=_order))

    async def _row(
        self,
        edge: Edge,
        target: Resolved,
        cards: dict[uuid.UUID, TodoLinkedCard],
        can_link: bool,
        principal: Principal,
    ) -> LinkRow:
        removable = LinkRights.may_touch(edge.kind, principal) and (
            can_link
            or (
                target.accessible
                and not target.granted
                and await self._changes(edge.target, principal)
            )
        )
        return LinkRow(
            id=edge.id,
            kind=edge.kind,  # pyright: ignore[reportArgumentType]
            target_id=edge.target_id,
            accessible=target.accessible,
            title=target.title if target.accessible else None,
            url=target.url if target.accessible else None,
            detail=target.detail if target.accessible else None,
            granted=target.granted,
            card=cards.get(edge.target_id) if edge.kind == "todo" else None,
            removable=removable,
            created_at=edge.created_at,
        )

    async def _check_change(self, one: LinkEnd, other: LinkEnd, principal: Principal) -> None:
        """Refuse a change of the link between ``one`` and ``other`` (spec 001404).

        Raises:
            ValidationProblem: ``link_target_not_found`` (HTTP 422).
            ForbiddenError: ``link_forbidden`` (HTTP 403), also for a cost centre end
                without a budget write right (spec 001410).
        """
        if not all(
            LinkRights.may_touch(end[0], principal)
            for end in (one, other)
            if end[0] == PAPERLESS_KIND
        ):
            raise ForbiddenError("A Paperless link needs paperless.use.", code="link_forbidden")
        for field_name, end in (("a", one), ("b", other)):
            if not await self._reads(end, principal):
                raise _invalid("The element was not found.", "link_target_not_found", field_name)
        if not (await self._changes(one, principal) or await self._changes(other, principal)):
            raise ForbiddenError("You may change neither element.", code="link_forbidden")
        if not all(LinkRights.may_touch(end[0], principal) for end in (one, other)):
            raise ForbiddenError(
                "A cost centre link needs a budget write right.", code="link_forbidden"
            )

    async def _prepare(self, one: LinkEnd, other: LinkEnd, principal: Principal) -> None:
        """Check and store the Paperless end of a new link (002763-002765).

        Raises:
            ValidationProblem: ``link_paperless_pair`` (HTTP 422).
            ForbiddenError: ``link_forbidden`` without ``paperless.use`` (HTTP 403).
            ServiceUnavailableError: ``paperless_unavailable`` (HTTP 503).
        """
        ends = [end for end in (one, other) if end[0] == PAPERLESS_KIND]
        if len(ends) > 1:
            raise _invalid(
                "Two Paperless documents cannot link each other.", "link_paperless_pair", "b"
            )
        if ends and not LinkRights.may_touch(PAPERLESS_KIND, principal):
            raise ForbiddenError("A Paperless link needs paperless.use.", code="link_forbidden")
        await self.todos.links.prepare(ends, principal)

    async def _cards(
        self, ends: Sequence[LinkEnd], principal: Principal
    ) -> list[tuple[LinkEnd, TodoCard, TodoBoard]]:
        """The card ends with their boards, locked for the change.

        The boards lock in the order of their ids, so two changes of the same two cards
        wait for each other and never deadlock, and the second sees the first link.
        """
        boards = [(await self._board_of(end[1]), end) for end in ends if end[0] == GRANTING_KIND]
        return [
            (end, *(await self.todos.card_end(end[1], principal, write=False)))
            for _board, end in sorted(boards, key=lambda pair: pair[0])
        ]

    async def _board_of(self, card_id: uuid.UUID) -> str:
        """The board id of a card as text, empty for a card that does not exist."""
        card = await self.session.get(TodoCard, card_id)
        return str(card.board_id) if card is not None else ""

    async def add(self, one: LinkEnd, other: LinkEnd, principal: Principal) -> None:
        """Link two elements; the caller commits, and a parallel equal link then fails.

        Raises:
            ValidationProblem: ``link_self``, ``link_paperless_pair`` or
                ``link_target_not_found`` (HTTP 422).
            ForbiddenError: ``link_forbidden`` (HTTP 403).
            ServiceUnavailableError: ``paperless_unavailable`` for a Paperless end while
                Paperless does not answer (HTTP 503).
            ConflictError: ``link_exists``, or ``event_link_taken`` when a card end is an
                Event and another Event links the Antrag, Buchung or invoice (HTTP 409).
        """
        if one == other:
            raise _invalid("An element cannot link itself.", "link_self", "b")
        if one[0] not in await link_kinds_on(self.session) or other[0] not in (
            await link_kinds_on(self.session)
        ):
            raise _invalid("The element was not found.", "link_target_not_found", "b")
        await self._prepare(one, other, principal)
        await self._check_change(one, other, principal)
        cards = await self._cards((one, other), principal)
        if await link_store.link_between(self.session, one, other) is not None:
            raise ConflictError("The elements are linked.", code="link_exists")
        actor = await self.todos.actor_of(principal)
        for end, card, _board in cards:
            await self.todos.check_new_link(card, other if end == one else one)
        link = Link.between(one, other, actor)
        self.session.add(link)
        await audit_link(self.session, AuditAction.LINK_ADD, link, principal)
        for end, card, board in cards:
            self.todos.note_link(card, board, other if end == one else one, actor, added=True)

    async def remove(self, link_id: uuid.UUID, principal: Principal) -> None:
        """Remove a link from both ends (spec 001401); the caller commits.

        Raises:
            NotFoundError: The link does not exist (HTTP 404).
            ValidationProblem: ``link_target_not_found`` (HTTP 422).
            ForbiddenError: ``link_forbidden`` (HTTP 403).
        """
        link = await self.session.get(Link, link_id)
        if link is None:
            raise NotFoundError(f"link {link_id} not found")
        one: LinkEnd = (link.a_kind, link.a_id)
        other: LinkEnd = (link.b_kind, link.b_id)
        await self._check_change(one, other, principal)
        actor = await self.todos.actor_of(principal)
        cards = await self._cards((one, other), principal)
        await audit_link(self.session, AuditAction.LINK_REMOVE, link, principal)
        await self.session.delete(link)
        for end, card, board in cards:
            self.todos.note_link(card, board, link.other(end), actor, added=False)

    async def view(self, link_id: uuid.UUID, principal: Principal) -> TodoLinkView:
        """The read sheet of the other end of a card that the principal reads (000487).

        Raises:
            NotFoundError: The link has no card end that the principal reads, or the other
                end has no sheet (HTTP 404).
        """
        link = await self.session.get(Link, link_id)
        if link is None:
            raise NotFoundError(f"link {link_id} not found")
        ends: tuple[LinkEnd, LinkEnd] = ((link.a_kind, link.a_id), (link.b_kind, link.b_id))
        targets = [
            link.other(end)
            for end in ends
            if end[0] == GRANTING_KIND and await self._reads(end, principal)
        ]
        if not targets:
            raise NotFoundError(f"link {link_id} not found")
        kind, target_id = targets[0]
        return await LinkViewer(self.session, self.todos.links).view(kind, target_id, principal)

    async def targets(
        self, q: str, kind: str, principal: Principal, *, exclude: LinkEnd | None = None
    ) -> list[TodoLinkTarget]:
        """Search the elements that the principal reads, without ``exclude`` and its links.

        A term below two characters lists the newest cards for the kind ``todo``
        (spec 001408). A cost centre is a hit only for a budget write right (spec 001410).
        """
        card = exclude[1] if exclude is not None and exclude[0] == "todo" else None
        searched = await self.todos.links.search(q, kind, principal, exclude_card_id=card)
        found = [t for t in searched if LinkRights.may_touch(t.kind, principal)]
        if exclude is None:
            return found
        taken = {
            exclude,
            *(e.target for e in await link_store.edges(self.session, exclude[0], [exclude[1]])),
        }
        return [t for t in found if (t.kind, t.target_id) not in taken]
