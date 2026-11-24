"""The notes of the team: add, edit, delete, with mentions and files."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from app.modules.auth.principal import Principal
from app.modules.files.drafts import bind_drafts, check_message_drafts
from app.modules.tickets.access import AreaScope
from app.modules.tickets.mail_send import is_mail_ticket, queue_answer
from app.modules.tickets.models import Ticket, TicketNote
from app.modules.tickets.schemas import NoteCreate, TicketNoteOut
from app.modules.tickets.service.common import TICKET_ANONYMIZED, _area_of, _now
from app.modules.tickets.service.reads import ReadOps
from app.shared.errors import ValidationProblem
from app.shared.mentions import (
    check_mentions,
    mention_ids,
    new_mentions,
    stored_mentions,
    unique_mentions,
)


class NoteOps(ReadOps):
    """Team notes on a ticket."""

    async def _checked_mentions(
        self, ticket: Ticket, mentions: Sequence[uuid.UUID], before: Sequence[uuid.UUID] = ()
    ) -> list[uuid.UUID]:
        """Return the mentions without duplicates, after the check against ``assignees``.

        Only the mentions that are not in ``before`` are checked, so an edit keeps a
        mention of a person who lost the work right since the create.

        Raises:
            ValidationProblem: A new mention of a person without the work right in the
                Bereich of the ticket (HTTP 422, ``mention_not_member``).
        """
        wanted = unique_mentions(mentions)
        added = new_mentions(wanted, before)
        if added:
            allowed = {p.principal_id for p in await self.assignees(_area_of(ticket))}
            check_mentions(added, {pid for pid in allowed if pid is not None})
        return wanted

    async def add_note(
        self,
        ticket_id: uuid.UUID,
        payload: NoteCreate,
        principal: Principal,
        *,
        pepper: str,
        areas: AreaScope = None,
    ) -> TicketNoteOut:
        """Add a note (``internal`` or ``public``) and bind its files.

        Raises:
            NotFoundError: No ticket has this id, or the caller has no account row
                (HTTP 404).
            ValidationProblem: Files on an anonymized ticket (``ticket_anonymized``),
                files without a draft token, or a draft that is missing, expired,
                foreign or infected, or a mention of a person without the work right
                in the Bereich (``mention_not_member``), or a public message on a mail
                ticket to nobody (``mail_without_recipient``) (HTTP 422).
            ConflictError: A public message on a mail ticket while the Postfach of the
                Bereich is off (``mailbox_off``, HTTP 409).

        A public message on a mail ticket is stored with its mail to ``to`` and ``cc``
        of the payload (§F/integrations/ticket-mail/002733, 002735).

        With files the ticket row is locked, so the retention cron (which locks it too)
        cannot anonymize the ticket between the check and the commit; the cron runs once
        and would not see the file again.
        """
        ticket = await self._get(ticket_id, lock=bool(payload.attachment_ids), areas=areas)
        author = await self._require_account(principal)
        wanted = await self._checked_mentions(ticket, payload.mentions)
        note = await self._insert_note(
            ticket,
            author,
            body=payload.body,
            visibility=payload.visibility,
            attachment_ids=payload.attachment_ids,
            draft_token=payload.draft_token,
            pepper=pepper,
            mentions=wanted,
            answer=(
                (payload.to, payload.cc)
                if payload.visibility == "public" and is_mail_ticket(ticket)
                else None
            ),
        )
        self.added_mentions = wanted
        return note

    async def _insert_note(
        self,
        ticket: Ticket,
        author: uuid.UUID,
        *,
        body: str,
        visibility: str,
        attachment_ids: list[uuid.UUID],
        draft_token: str | None,
        pepper: str,
        for_reporter: bool = False,
        mentions: Sequence[uuid.UUID] = (),
        answer: tuple[Sequence[str] | None, Sequence[str] | None] | None = None,
    ) -> TicketNoteOut:
        """Store a note, bind its files and commit. The caller read the ticket.

        ``answer`` holds ``to`` and ``cc`` of the mail of the note; None sends no mail.
        """
        if attachment_ids and ticket.anonymized_at is not None:
            raise ValidationProblem(
                "The ticket is anonymized and takes no files.",
                code=TICKET_ANONYMIZED,
                errors=[{"field": "attachmentIds", "msg": "ticket is anonymized"}],
            )
        token = await check_message_drafts(
            self.session,
            attachment_ids=attachment_ids,
            token=draft_token,
            pepper=pepper,
        )
        note = TicketNote(
            id=uuid.uuid4(),
            ticket_id=ticket.id,
            author_id=author,
            body=body,
            visibility=visibility,
            mentions=stored_mentions(mentions),
        )
        self.session.add(note)
        if token is not None:
            await self.session.flush()
            await bind_drafts(
                self.session,
                attachment_ids=attachment_ids,
                token=token,
                pepper=pepper,
                ticket_note_id=note.id,
            )
        if answer is not None:
            await self.session.flush()
            await queue_answer(self.session, ticket, note.id, to=answer[0], cc=answer[1])
        ticket.updated_at = _now()
        await self.session.commit()
        await self.session.refresh(note)
        return await self._note_out(note, author, ticket, for_reporter=for_reporter)

    async def edit_note(
        self,
        ticket_id: uuid.UUID,
        note_id: uuid.UUID,
        body: str,
        principal: Principal,
        *,
        mentions: Sequence[uuid.UUID] | None = None,
        areas: AreaScope = None,
    ) -> TicketNoteOut:
        """Change the text of an own note and set ``edited_at``; the files stay.

        ``mentions`` None keeps the stored mentions; a list replaces them after the
        check of ``add_note``. ``added_mentions`` holds the ids that the list adds.

        Raises:
            NotFoundError: No live note with this id on this ticket (HTTP 404).
            ForbiddenError: The note has another author (HTTP 403, ``not_note_author``).
            ValidationProblem: A mention of a person without the work right in the
                Bereich (HTTP 422, ``mention_not_member``).
        """
        if areas is not None:
            await self._get(ticket_id, areas=areas)
        note, me = await self._own_note(ticket_id, note_id, principal)
        ticket = await self._get(ticket_id)
        self.added_mentions = []
        before = mention_ids(note.mentions)
        wanted = (
            await self._checked_mentions(ticket, mentions, before) if mentions is not None else None
        )
        if wanted is not None:
            self.added_mentions = new_mentions(wanted, before)
            note.mentions = stored_mentions(wanted)
        note.body = body
        note.edited_at = _now()
        await self.session.commit()
        return await self._note_out(note, me, ticket)

    async def delete_note(
        self,
        ticket_id: uuid.UUID,
        note_id: uuid.UUID,
        principal: Principal,
        *,
        areas: AreaScope = None,
    ) -> None:
        """Soft-delete an own note (``deleted_at``) and remove its files.

        Raises:
            NotFoundError: No live note with this id on this ticket (HTTP 404).
            ForbiddenError: The note has another author (HTTP 403, ``not_note_author``).
        """
        if areas is not None:
            await self._get(ticket_id, areas=areas)
        note, _me = await self._own_note(ticket_id, note_id, principal)
        note.deleted_at = _now()
        await self.files.delete_for_messages("ticket_note", [note.id], actor=principal.sub)
        await self.session.commit()
