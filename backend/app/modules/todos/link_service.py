"""Links between any two elements: list, add, remove, search and the read sheet.

The routes of ``/api/links`` (spec 001409) use this service. A link has no direction
(spec 001401): it shows in ``Verknüpft`` of both ends. The rules:

* Any two elements of the kinds of ``LINK_KINDS`` link, also two of one kind, never an
  element to itself, at most once per pair (spec 001400).
* A person adds or removes a link when the person reads both ends by the rule of their
  kind and may change at least one of them (spec 001404, ``LinkRights``).
* Only a card gives read access to its links (specs 000487, 001405): the links of a
  card resolve with ``grants``, the links of any other element without.
* A link with a card end writes the card events ``linked`` and ``unlinked`` and touches
  the board, and an Event keeps its Antrag, Buchung or invoice to itself
  (``event_link_taken``).

The list shows a linked Event first, then the other links in the order of the kinds of
``LINK_KINDS``, and in each kind the newest link first (spec 001407).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.principal import Principal
from app.modules.todos import link_store
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


def _invalid(msg: str, code: str, field_name: str) -> ValidationProblem:
    return ValidationProblem(msg, code=code, errors=[{"field": field_name, "msg": msg}])


def _order(row: LinkRow) -> tuple[bool, int, float]:
    """A linked Event first, then by kind, then the newest first."""
    return (
        row.card is None or row.card.event is None,
        LINK_KINDS.index(row.kind),
        -row.created_at.timestamp(),
    )


class LinkService:
    """The links of the elements, as one principal sees and changes them."""

    def __init__(self, session: AsyncSession, todos: TodoService | None = None) -> None:
        """Bind the service to a session; the to-do service gives the cards and the rules."""
        self.session = session
        self.todos = todos or TodoService(session)
        self.rights = LinkRights(session, self.todos.access)

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
        can_link = await self._changes(own, principal)
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
        removable = can_link or (
            target.accessible and not target.granted and await self._changes(edge.target, principal)
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
            ForbiddenError: ``link_forbidden`` (HTTP 403).
        """
        for field_name, end in (("a", one), ("b", other)):
            if not await self._reads(end, principal):
                raise _invalid("The element was not found.", "link_target_not_found", field_name)
        if not (await self._changes(one, principal) or await self._changes(other, principal)):
            raise ForbiddenError("You may change neither element.", code="link_forbidden")

    async def _cards(
        self, ends: Sequence[LinkEnd], principal: Principal
    ) -> list[tuple[LinkEnd, TodoCard, TodoBoard]]:
        """The card ends with their boards, locked for the change.

        The boards lock in the order of their ids, so two changes of the same two cards
        wait for each other and never deadlock, and the second sees the first link.
        """
        boards: list[tuple[str, LinkEnd]] = []
        for end in ends:
            if end[0] != "todo":
                continue
            card = await self.session.get(TodoCard, end[1])
            boards.append((str(card.board_id) if card is not None else "", end))
        return [
            (end, *(await self.todos.card_end(end[1], principal, write=False)))
            for _board, end in sorted(boards, key=lambda pair: pair[0])
        ]

    async def _commit_new(self) -> None:
        """Commit a new link; a parallel equal link is ``link_exists``.

        Raises:
            ConflictError: ``link_exists`` (HTTP 409).
        """
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ConflictError("The elements are linked.", code="link_exists") from exc

    async def add(self, one: LinkEnd, other: LinkEnd, principal: Principal) -> LinksOut:
        """Link two elements and return the links of ``one``.

        Raises:
            ValidationProblem: ``link_self`` or ``link_target_not_found`` (HTTP 422).
            ForbiddenError: ``link_forbidden`` (HTTP 403).
            ConflictError: ``link_exists``, or ``event_link_taken`` when a card end is an
                Event and another Event links the Antrag, Buchung or invoice (HTTP 409).
        """
        if one == other:
            raise _invalid("An element cannot link itself.", "link_self", "b")
        if one[0] not in await link_kinds_on(self.session) or other[0] not in (
            await link_kinds_on(self.session)
        ):
            raise _invalid("The element was not found.", "link_target_not_found", "b")
        await self._check_change(one, other, principal)
        cards = await self._cards((one, other), principal)
        if await link_store.link_between(self.session, one, other) is not None:
            raise ConflictError("The elements are linked.", code="link_exists")
        actor = await self.todos.actor_of(principal)
        for end, card, _board in cards:
            await self.todos.check_new_link(card, other if end == one else one)
        self.session.add(Link.between(one, other, actor))
        for end, card, board in cards:
            self.todos.note_link(card, board, other if end == one else one, actor, added=True)
        await self._commit_new()
        return await self.of(one[0], one[1], principal)

    async def remove(self, link_id: uuid.UUID, principal: Principal) -> None:
        """Remove a link from both ends (spec 001401).

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
        await self.session.delete(link)
        for end, card, board in cards:
            self.todos.note_link(card, board, link.other(end), actor, added=False)
        await self.session.commit()

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
        (spec 001408).
        """
        card = exclude[1] if exclude is not None and exclude[0] == "todo" else None
        found = await self.todos.links.search(q, kind, principal, exclude_card_id=card)
        if exclude is None:
            return found
        taken = {
            exclude,
            *(e.target for e in await link_store.edges(self.session, exclude[0], [exclude[1]])),
        }
        return [t for t in found if (t.kind, t.target_id) not in taken]
