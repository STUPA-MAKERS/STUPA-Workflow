"""Pure serialization of tickets, notes, mails, events and persons into the API schemas."""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet
from typing import Literal

from pydantic import JsonValue

from app.modules.auth.people import DELETED_PERSON, PersonRef, person_of
from app.modules.files.schemas import MessageAttachmentOut
from app.modules.tickets.models import (
    TICKET_MAIL_STATES,
    Ticket,
    TicketEvent,
    TicketMail,
    TicketNote,
    TicketSenderBlock,
)
from app.modules.tickets.numbers import format_number
from app.modules.tickets.schemas import (
    TicketBlockedSender,
    TicketEventOut,
    TicketMailOut,
    TicketNoteOut,
    TicketRef,
    TicketReporter,
    TicketSkippedFile,
)
from app.modules.tickets.service.common import _Account, _uuid_or_none
from app.shared.mentions import mention_ids


def _blocked_sender(
    row: TicketSenderBlock, accounts: Mapping[uuid.UUID, _Account], numbers: Mapping[uuid.UUID, str]
) -> TicketBlockedSender:
    """Build the wire form of one block from the loaded accounts and ticket numbers."""
    account = accounts.get(row.principal_id) if row.principal_id is not None else None
    source = numbers.get(row.source_ticket_id) if row.source_ticket_id else None
    return TicketBlockedSender(
        id=row.id,
        kind="principal" if row.principal_id is not None else "email",
        person=_person(accounts, row.principal_id) if row.principal_id is not None else None,
        email=account.email if account is not None else row.email,
        blocked_by=_person(accounts, row.created_by) if row.created_by is not None else None,
        blocked_at=row.created_at,
        source_ticket=(
            TicketRef(id=row.source_ticket_id, number=format_number(source))
            if row.source_ticket_id is not None and source is not None
            else None
        ),
        hit_count=row.hit_count,
        last_hit_at=row.last_hit_at,
    )


def _ids_of(payload: Mapping[str, JsonValue]) -> frozenset[uuid.UUID]:
    raws = (payload.get("from"), payload.get("to"))
    return frozenset(uuid.UUID(raw) for raw in raws if isinstance(raw, str))


def _people_of(
    notes: Sequence[TicketNote], events: Sequence[TicketEvent]
) -> frozenset[uuid.UUID | None]:
    """Return the accounts that a ticket detail names: authors, mentions, actors, assignees."""
    return frozenset(
        {
            *(n.author_id for n in notes),
            *(pid for n in notes for pid in mention_ids(n.mentions)),
            *(e.actor_id for e in events),
            *(pid for e in events if e.kind == "assignee" for pid in _ids_of(e.payload)),
        }
    )


def _person(accounts: Mapping[uuid.UUID, _Account], principal_id: uuid.UUID | None) -> PersonRef:
    account = accounts.get(principal_id) if principal_id is not None else None
    if principal_id is None or account is None:
        return DELETED_PERSON
    return person_of(principal_id, account.display_name, account.email)


def _note_row(
    note: TicketNote,
    ticket: Ticket,
    accounts: dict[uuid.UUID, _Account],
    me: uuid.UUID | None,
    attachments: list[MessageAttachmentOut],
    *,
    for_reporter: bool = False,
    mail: TicketMail | None = None,
) -> TicketNoteOut:
    """Build the wire note.

    For the reporter a team author shows by name only: neither the e-mail nor the
    account id of a holder of ``ticket.manage`` reaches the reporter, because the id
    opens the avatar of that e-mail. For the same reason the reporter gets no
    mentions (an empty list).
    """
    author = (
        _reporter_view_author(note.author_id, accounts, me)
        if for_reporter and note.author_id is not None
        else _mail_author(mail)
        if mail is not None and note.author_id is None
        else _person(accounts, note.author_id)
    )
    return TicketNoteOut(
        id=note.id,
        author=author,
        body=note.body,
        at=note.created_at,
        edited_at=note.edited_at,
        is_own=me is not None and note.author_id == me,
        attachments=attachments,
        visibility=note.visibility or "internal",  # pyright: ignore[reportArgumentType]
        from_reporter=(
            (note.author_id is not None and note.author_id == ticket.reporter_principal_id)
            or (note.author_id is None and mail is not None and mail.direction == "in")
        ),
        mentions=(
            ()
            if for_reporter
            else tuple(_person(accounts, pid) for pid in mention_ids(note.mentions))
        ),
    )


def _mail_author(mail: TicketMail) -> PersonRef:
    """Return the writer of a message from a mail: the name of ``From``, else the address."""
    name = mail.from_name or mail.from_address
    return PersonRef(principal_id=None, display_name=name) if name else DELETED_PERSON


def _mail_source_state(mail: TicketMail) -> Literal["clean", "infected", "closed", "gone"]:
    if mail.source_key is None:
        return "gone"
    if mail.source_scan is None:
        return "closed"
    return "clean" if mail.source_scan == "clean" else "infected"


def _mail_out(mail: TicketMail) -> TicketMailOut:
    return TicketMailOut(
        id=mail.id,
        note_id=mail.note_id,
        direction="out" if mail.direction == "out" else "in",
        from_name=mail.from_name,
        from_address=mail.from_address,
        cc=tuple(str(entry) for entry in mail.cc or []),
        subject=mail.subject,
        automatic=mail.automatic,
        sender_checked=mail.sender_checked,
        source=_mail_source_state(mail),
        source_size=mail.source_size,
        skipped=tuple(TicketSkippedFile.model_validate(entry) for entry in mail.skipped or []),
        to=tuple(str(entry) for entry in mail.to_addresses or []),
        state=mail.state if mail.state in TICKET_MAIL_STATES else None,  # pyright: ignore[reportArgumentType]
        error=mail.send_error if mail.state != "sent" else None,
        at=mail.created_at,
    )


def _reporter_view_author(
    author_id: uuid.UUID, accounts: Mapping[uuid.UUID, _Account], me: uuid.UUID | None
) -> PersonRef:
    """Return a note author as the reporter sees it: the name, the id only of the own account."""
    account = accounts.get(author_id)
    own = account is not None and author_id == me
    return PersonRef(
        principal_id=author_id if own else None,
        display_name=account.display_name if account is not None else None,
    )


def _reporter(ticket: Ticket, accounts: dict[uuid.UUID, _Account]) -> TicketReporter:
    if ticket.anonymized_at is not None:
        return TicketReporter(anonymized=True)
    if ticket.reporter_principal_id is None:
        return TicketReporter(display_name=ticket.reporter_name, email=ticket.reporter_email)
    person = _person(accounts, ticket.reporter_principal_id)
    account = accounts.get(ticket.reporter_principal_id)
    return TicketReporter(
        principal_id=person.principal_id,
        display_name=person.display_name,
        email=account.email if account is not None else None,
    )


def _event_out(
    event: TicketEvent,
    accounts: dict[uuid.UUID, _Account],
    readable_cards: set[uuid.UUID] | None = None,
) -> TicketEventOut:
    """Build the API form of a ticket event.

    The card title of a ``todo_done`` event shows only to a reader of the board of the card.
    """
    return TicketEventOut(
        id=event.id,
        kind=event.kind,  # pyright: ignore[reportArgumentType]
        actor=_person(accounts, event.actor_id) if event.actor_id is not None else None,
        at=event.created_at,
        payload=_event_payload(event, accounts, readable_cards or frozenset()),
    )


def _event_payload(
    event: TicketEvent,
    accounts: Mapping[uuid.UUID, _Account],
    readable_cards: AbstractSet[uuid.UUID],
) -> dict[str, JsonValue]:
    """Return the payload of an event as the detail shows it.

    A ``todo_done`` event of an unreadable card loses its title, and an ``assignee``
    event names people instead of ids.
    """
    payload: dict[str, JsonValue] = dict(event.payload or {})
    match event.kind:
        case "todo_done" if _uuid_or_none(payload.get("cardId")) not in readable_cards:
            return {**payload, "cardTitle": None}
        case "assignee":
            people = {key: _person_json(accounts, payload.get(key)) for key in ("from", "to")}
            return {**payload, **people}
        case _:
            return payload


def _person_json(accounts: Mapping[uuid.UUID, _Account], raw: JsonValue) -> JsonValue:
    """Return the JSON form of the person of an id in an event payload, else None."""
    return (
        _person(accounts, uuid.UUID(raw)).model_dump(by_alias=True, mode="json")
        if isinstance(raw, str)
        else None
    )
