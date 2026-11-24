"""Creation of a ticket: the report of the help menu and the ticket by hand."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.files.drafts import bind_drafts, check_drafts
from app.modules.tickets.access import AreaScope, works_in
from app.modules.tickets.mail_send import queue_answer
from app.modules.tickets.models import (
    PLATFORM_AREA_ID,
    Ticket,
    TicketArea,
    TicketCategory,
    TicketEvent,
    TicketMailbox,
    TicketNote,
)
from app.modules.tickets.schemas import TicketCreate, TicketManualCreate
from app.modules.tickets.service.blocks import BlockOps
from app.modules.tickets.service.common import (
    AREA_NEEDS_SESSION,
    AREA_NOT_REACHABLE,
    AREA_WITHOUT_MAILBOX,
    REPORTER_INVALID,
    SwallowedReport,
    normalize_email,
)
from app.modules.tickets.webhook_fields import emit_ticket_created
from app.shared.errors import ForbiddenError, ValidationProblem


class CreateOps(BlockOps):
    """The public report and the ticket by hand."""

    async def create(
        self,
        payload: TicketCreate,
        *,
        reporter_id: uuid.UUID | None,
        email: str | None,
        pepper: str,
    ) -> Ticket | SwallowedReport:
        """Store a report, bind its draft attachments and write the ``created`` event.

        ``reporter_id`` is the account of a session, else ``email`` is the address of
        the reporter. The router makes sure that one of them is set.

        A report of a blocked sender (``matching_block``) passes every check of a
        normal report first, so its errors look the same. It then draws a number
        and stores nothing: no ticket, no event, no bind. The
        result is a ``SwallowedReport`` and the router sends no mail. The drafts stay
        unbound until the purge.

        ``areaId`` names the Bereich, else the report goes to ``Plattform``. A Bereich
        other than ``Plattform`` takes a report only from an account and only while
        its switch ``in_app`` is on.

        Raises:
            ForbiddenError: A report to a Bereich other than ``Plattform`` without an
                account (``ticket_area_needs_session``), or to a Bereich without the
                switch (``ticket_area_not_reachable``) (HTTP 403).
            ValidationProblem: Attachments without a draft token, or a draft that is
                missing, expired, foreign or infected; an unknown Bereich
                (``area_invalid``), a missing kind for ``Plattform``, or a Kategorie
                of another Bereich (``category_invalid``) (HTTP 422).
        """
        area_id = await self._report_area(payload, reporter_id)
        await self._check_kind(area_id, payload.kind, payload.category_id)
        if payload.attachment_ids and not payload.draft_token:
            raise ValidationProblem(
                "Attachments need the draft token of their upload.",
                errors=[{"field": "draftToken", "msg": "required with attachmentIds"}],
            )
        if payload.attachment_ids and payload.draft_token:
            await check_drafts(
                self.session,
                attachment_ids=payload.attachment_ids,
                token=payload.draft_token,
                pepper=pepper,
            )
        block_id = await self.matching_block(reporter_id=reporter_id, email=email)
        if block_id is not None:
            return await self._swallow(block_id)
        ticket = Ticket(
            id=uuid.uuid4(),
            number=await self.free_number(),
            area_id=area_id,
            kind=payload.kind,
            category_id=payload.category_id,
            source="help",
            title=payload.title.strip() or payload.title,
            body=payload.body,
            status="new",
            reporter_principal_id=reporter_id,
            reporter_email=None if reporter_id is not None else email,
            context=payload.context.model_dump(by_alias=True, exclude_none=True),
        )
        self.session.add(ticket)
        await self.session.flush()
        if payload.attachment_ids and payload.draft_token:
            await bind_drafts(
                self.session,
                attachment_ids=payload.attachment_ids,
                token=payload.draft_token,
                pepper=pepper,
                ticket_id=ticket.id,
            )
        reporter = await self.reporter_address(ticket)
        confirmation = reporter is not None
        await emit_ticket_created(self.session, ticket, reporter_email=reporter)
        self.session.add(
            TicketEvent(
                ticket_id=ticket.id,
                actor_id=reporter_id,
                kind="created",
                payload={"confirmationSent": confirmation},
            )
        )
        await self.session.commit()
        return ticket

    async def _report_area(self, payload: TicketCreate, reporter_id: uuid.UUID | None) -> uuid.UUID:
        """Return the Bereich of a report, after the check of the switch ``in_app``.

        The check of the account comes first, so a person without a session learns
        nothing about the Bereiche.
        """
        if payload.area_id is None or payload.area_id == PLATFORM_AREA_ID:
            return PLATFORM_AREA_ID
        if reporter_id is None:
            raise ForbiddenError(
                "Only the Bereich Plattform takes a report without a login.",
                code=AREA_NEEDS_SESSION,
            )
        area = await self.session.get(TicketArea, payload.area_id)
        if area is None:
            raise ValidationProblem(
                "The Bereich does not exist.",
                code="area_invalid",
                errors=[{"field": "areaId", "msg": "unknown Bereich"}],
            )
        if not area.in_app:
            raise ForbiddenError(
                "The Bereich takes no tickets from the app.", code=AREA_NOT_REACHABLE
            )
        return area.id

    async def _check_kind(
        self, area_id: uuid.UUID, kind: str | None, category_id: uuid.UUID | None
    ) -> None:
        """Check the kind and the Kategorie of a new ticket against its Bereich.

        Raises:
            ValidationProblem: ``Plattform`` without a kind, a kind outside
                ``Plattform``, or a Kategorie of another Bereich (HTTP 422).
        """
        if area_id == PLATFORM_AREA_ID and kind is None:
            raise ValidationProblem(
                "A ticket of the Bereich Plattform needs a kind.",
                errors=[{"field": "kind", "msg": "required for Plattform"}],
            )
        category = (
            await self.session.get(TicketCategory, category_id) if category_id is not None else None
        )
        foreign = category_id is not None and (category is None or category.area_id != area_id)
        if foreign or (kind is not None and area_id != PLATFORM_AREA_ID):
            raise ValidationProblem(
                "The Kategorie does not belong to the Bereich of the ticket.",
                code="category_invalid",
                errors=[{"field": "categoryId", "msg": "not a Kategorie of the Bereich"}],
            )

    async def create_manual(
        self,
        payload: TicketManualCreate,
        principal: Principal,
        *,
        areas: AreaScope = None,
    ) -> tuple[Ticket, TicketNote | None]:
        """Store a ticket that a person of the team writes for an account, without a commit.

        The source is ``team``. ``body`` is the note of the team; the view of the
        person leaves it out. ``message`` becomes the first public note. The result is
        the ticket and that note, else None.

        A ticket for an address needs a Postfach of the Bereich, because the first
        public message goes out as a mail (§F/collaboration/tickets/002712). The
        message of such a ticket is stored with its mail.

        Raises:
            ForbiddenError: The caller has no work right in the Bereich (HTTP 403).
            NotFoundError: The caller has no account row (HTTP 404).
            ValidationProblem: An unknown Bereich (``area_invalid``), an address in a
                Bereich without a Postfach (``ticket_area_without_mailbox``), no person
                or two, or an unknown or inactive account
                (``ticket_reporter_invalid``), a bad kind or Kategorie (HTTP 422).
            ConflictError: A message for an address while the Postfach is off (HTTP
                409, ``mailbox_off``).
        """
        if not works_in(areas, payload.area_id):
            raise ForbiddenError("No work right in the Bereich.")
        actor = await self._require_account(principal)
        if await self.session.get(TicketArea, payload.area_id) is None:
            raise ValidationProblem(
                "The Bereich does not exist.",
                code="area_invalid",
                errors=[{"field": "areaId", "msg": "unknown Bereich"}],
            )
        if (payload.reporter_id is None) == (payload.email is None):
            raise ValidationProblem(
                "A ticket names exactly one person: an account or an address.",
                code=REPORTER_INVALID,
                errors=[{"field": "reporterId", "msg": "exactly one of reporterId and email"}],
            )
        person = await self._manual_person(payload)
        await self._check_kind(payload.area_id, payload.kind, payload.category_id)
        address = normalize_email(payload.email) if payload.email is not None else None
        ticket = Ticket(
            id=uuid.uuid4(),
            number=await self.free_number(),
            area_id=payload.area_id,
            kind=payload.kind,
            category_id=payload.category_id,
            source="team",
            title=payload.title.strip() or payload.title,
            body=payload.body,
            status="new",
            reporter_principal_id=person.id if person is not None else None,
            reporter_email=address,
            context={},
        )
        self.session.add(ticket)
        await self.session.flush()
        await emit_ticket_created(
            self.session, ticket, reporter_email=person.email if person is not None else address
        )
        self._event(ticket, "created", actor, {"confirmationSent": False})
        note = (
            TicketNote(
                id=uuid.uuid4(),
                ticket_id=ticket.id,
                author_id=actor,
                body=payload.message,
                visibility="public",
                mentions=[],
            )
            if payload.message.strip()
            else None
        )
        if note is not None:
            self.session.add(note)
        await self.session.flush()
        if note is not None and person is None:
            await queue_answer(self.session, ticket, note.id)
        return ticket, note

    async def _manual_person(self, payload: TicketManualCreate) -> PrincipalRow | None:
        """Return the account of a ticket by hand; None for a ticket for an address.

        Raises:
            ValidationProblem: The Bereich has no Postfach for the address
                (``ticket_area_without_mailbox``), or the account is unknown or not
                active (``ticket_reporter_invalid``) (HTTP 422).
        """
        if payload.reporter_id is None:
            box = await self.session.scalar(
                select(TicketMailbox.id).where(TicketMailbox.area_id == payload.area_id)
            )
            if box is None:
                raise ValidationProblem(
                    "The Bereich has no Postfach, so it cannot write to an address.",
                    code=AREA_WITHOUT_MAILBOX,
                    errors=[{"field": "email", "msg": "the Bereich has no Postfach"}],
                )
            return None
        person = await self.session.get(PrincipalRow, payload.reporter_id)
        if person is None or not person.active or person.merged_into is not None:
            raise ValidationProblem(
                "The account does not exist or is not active.",
                code=REPORTER_INVALID,
                errors=[{"field": "reporterId", "msg": "unknown or inactive account"}],
            )
        return person
