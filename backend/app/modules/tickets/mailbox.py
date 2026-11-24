"""The Postfach of a Bereich: the read, the save, the delete and the connection test.

A Bereich has at most one Postfach (§F/integrations/ticket-mail/002720). A save checks
both hosts against the deploy setting ``TICKET_MAIL_HOST_ALLOWLIST``
(§NF/security/network/002744) and writes an audit entry that names the changed fields
and never a password (§F/integrations/ticket-mail/002743). No read returns a password
(§NF/security/network/002746).

No method here commits. The router owns the transaction.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.tickets import mail_client
from app.modules.tickets.mail_client import MailAccount
from app.modules.tickets.mailbox_schemas import (
    MailboxCheck,
    MailboxCreate,
    MailboxList,
    MailboxOut,
    MailboxPatch,
    MailboxTestOut,
)
from app.modules.tickets.models import TicketArea, TicketMailbox
from app.settings import Settings
from app.shared.errors import ConflictError, NotFoundError, ValidationProblem

#: The problem code of a second Postfach of one Bereich.
MAILBOX_EXISTS = "ticket_mailbox_exists"
#: The problem code of an account change without its password.
PASSWORD_REQUIRED = "password_required"
#: The columns of each account whose change needs the password of that account again.
_LOGIN_FIELDS: Mapping[str, frozenset[str]] = {
    kind: frozenset({f"{kind}_host", f"{kind}_port", f"{kind}_user"}) for kind in ("imap", "smtp")
}
#: The problem code of a host outside ``TICKET_MAIL_HOST_ALLOWLIST``.
HOST_NOT_ALLOWED = "mail_host_not_allowed"
#: The failed fetch runs in sequence after which the admin page shows the error.
SHOWN_FAILURES = 8
#: The wire names of the fields of a Postfach, by column.
_WIRE: Mapping[str, str] = {
    "address": "address",
    "imap_host": "imapHost",
    "imap_port": "imapPort",
    "imap_user": "imapUser",
    "imap_password": "imapPassword",
    "smtp_host": "smtpHost",
    "smtp_port": "smtpPort",
    "smtp_user": "smtpUser",
    "smtp_password": "smtpPassword",
    "done_folder": "doneFolder",
    "enabled": "enabled",
    "signature": "signature",
    "confirm": "confirm",
}
#: The columns whose change starts the fetch of the inbox from its first mail.
_INBOX_FIELDS = frozenset({"imap_host", "imap_port", "imap_user"})

Check = Callable[[MailAccount], str | None]


def host_allowed(host: str, port: int, allowlist: Sequence[str]) -> bool:
    """Tell whether the host, or the host with its port, is in the allowlist.

    An empty list allows no host.
    """
    allowed = frozenset(entry.strip().lower() for entry in allowlist if entry.strip())
    name = host.strip().lower()
    return name in allowed or f"{name}:{port}" in allowed


def _require_passwords(changed: Collection[str], sent: Collection[str]) -> None:
    """Refuse a change of host, port or user of an account that leaves out its password.

    A stored password must not follow a new host (§F/integrations/ticket-mail/002812).

    Raises:
        ValidationProblem: An account changes without its password (HTTP 422,
            ``password_required``).
    """
    missing = tuple(
        f"{kind}_password"
        for kind, fields in _LOGIN_FIELDS.items()
        if fields & set(changed) and f"{kind}_password" not in sent
    )
    if missing:
        raise ValidationProblem(
            "A change of host, port or user needs the password of that account again.",
            code=PASSWORD_REQUIRED,
            errors=[{"field": _WIRE[name], "msg": "password required"} for name in missing],
        )


def imap_account(row: TicketMailbox) -> MailAccount:
    """The IMAP account of a Postfach."""
    return MailAccount(row.imap_host, row.imap_port, row.imap_user, row.imap_password)


def smtp_account(row: TicketMailbox) -> MailAccount:
    """The SMTP account of a Postfach."""
    return MailAccount(row.smtp_host, row.smtp_port, row.smtp_user, row.smtp_password)


def mailbox_out(row: TicketMailbox) -> MailboxOut:
    """The wire form of a Postfach, without its passwords."""
    return MailboxOut(
        area_id=row.area_id,
        address=row.address,
        imap_host=row.imap_host,
        imap_port=row.imap_port,
        imap_user=row.imap_user,
        smtp_host=row.smtp_host,
        smtp_port=row.smtp_port,
        smtp_user=row.smtp_user,
        done_folder=row.done_folder,
        enabled=bool(row.enabled),
        signature=row.signature or "",
        confirm=bool(row.confirm),
        error=row.last_error if (row.failures or 0) >= SHOWN_FAILURES else None,
        fetched_at=row.fetched_at,
    )


@dataclass(frozen=True, slots=True)
class TicketMailboxService:
    """The Postfächer of the Bereiche, bound to one session."""

    session: AsyncSession
    settings: Settings
    check_imap: Check = mail_client.check_imap
    check_smtp: Check = mail_client.check_smtp

    async def listing(self) -> MailboxList:
        """List each Postfach and the hosts that the deploy settings allow."""
        rows = (
            await self.session.scalars(select(TicketMailbox).order_by(TicketMailbox.created_at))
        ).all()
        return MailboxList(
            items=tuple(mailbox_out(row) for row in rows),
            allowed_hosts=tuple(self.settings.ticket_mail_host_allowlist),
        )

    async def of_area(self, area_id: uuid.UUID) -> TicketMailbox | None:
        """Return the Postfach of a Bereich, else None."""
        return await self.session.scalar(
            select(TicketMailbox).where(TicketMailbox.area_id == area_id)
        )

    async def _get(self, area_id: uuid.UUID) -> TicketMailbox:
        row = await self.of_area(area_id)
        if row is None:
            raise NotFoundError(f"ticket area {area_id} has no mailbox")
        return row

    def _check_hosts(self, values: Mapping[str, object]) -> None:
        """Check both hosts against the allowlist.

        Raises:
            ValidationProblem: A host is not in the list (HTTP 422,
                ``mail_host_not_allowed``).
        """
        allowlist = self.settings.ticket_mail_host_allowlist
        errors = [
            {"field": _WIRE[f"{kind}_host"], "msg": "host not allowed"}
            for kind in ("imap", "smtp")
            if not host_allowed(
                str(values[f"{kind}_host"]), int(str(values[f"{kind}_port"])), allowlist
            )
        ]
        if errors:
            raise ValidationProblem(
                "A host of the Postfach is not in TICKET_MAIL_HOST_ALLOWLIST.",
                code=HOST_NOT_ALLOWED,
                errors=errors,
            )

    async def create(self, area_id: uuid.UUID, payload: MailboxCreate, actor: str) -> MailboxOut:
        """Give a Bereich its Postfach.

        Raises:
            NotFoundError: No Bereich has this id (HTTP 404).
            ConflictError: The Bereich has a Postfach (HTTP 409,
                ``ticket_mailbox_exists``).
            ValidationProblem: A host is not allowed (HTTP 422).
        """
        if await self.session.get(TicketArea, area_id) is None:
            raise NotFoundError(f"ticket area {area_id} not found")
        if await self.of_area(area_id) is not None:
            raise ConflictError("The Bereich has a Postfach.", code=MAILBOX_EXISTS)
        values = payload.model_dump()
        self._check_hosts(values)
        row = TicketMailbox(id=uuid.uuid4(), area_id=area_id, **values)
        self.session.add(row)
        await self.session.flush()
        await self._audit(actor, area_id, "create", sorted(_WIRE[name] for name in values), row)
        return mailbox_out(row)

    async def patch(self, area_id: uuid.UUID, payload: MailboxPatch, actor: str) -> MailboxOut:
        """Change the Postfach of a Bereich. A field that the body leaves out stays.

        A change of the IMAP host, port or user starts the fetch from the first mail of
        the new inbox; the identity of a mail keeps a second import away
        (§F/integrations/ticket-mail/002724).

        Raises:
            NotFoundError: The Bereich has no Postfach (HTTP 404).
            ValidationProblem: A host is not allowed (HTTP 422).
        """
        row = await self._get(area_id)
        sent = payload.model_dump(exclude_unset=True, exclude_none=True)
        changed = {name: value for name, value in sent.items() if getattr(row, name) != value}
        _require_passwords(changed.keys(), sent.keys())
        if changed:
            self._check_hosts({name: changed.get(name, getattr(row, name)) for name in _WIRE})
        reset: dict[str, object] = (
            {"uid_validity": None, "last_uid": 0} if _INBOX_FIELDS & set(changed) else {}
        )
        cleared: dict[str, object] = {"failures": 0, "last_error": None} if changed else {}
        for name, value in {**changed, **reset, **cleared}.items():
            setattr(row, name, value)
        await self.session.flush()
        if changed:
            await self._audit(actor, area_id, "update", sorted(_WIRE[n] for n in changed), row)
        return mailbox_out(row)

    async def delete(self, area_id: uuid.UUID, actor: str) -> None:
        """Remove the Postfach of a Bereich.

        Raises:
            NotFoundError: The Bereich has no Postfach (HTTP 404).
        """
        row = await self._get(area_id)
        await self.session.delete(row)
        await self.session.flush()
        await self._audit(actor, area_id, "delete", [], row)

    async def test(self, area_id: uuid.UUID) -> MailboxTestOut:
        """Log in to both accounts of the stored Postfach and tell each result.

        Raises:
            NotFoundError: The Bereich has no Postfach (HTTP 404).
        """
        row = await self._get(area_id)
        imap, smtp = await asyncio.gather(
            asyncio.to_thread(self.check_imap, imap_account(row)),
            asyncio.to_thread(self.check_smtp, smtp_account(row)),
        )
        return MailboxTestOut(
            imap=MailboxCheck(ok=imap is None, error=imap),
            smtp=MailboxCheck(ok=smtp is None, error=smtp),
        )

    async def _audit(
        self, actor: str, area_id: uuid.UUID, op: str, fields: list[str], row: TicketMailbox
    ) -> None:
        await audit_record(
            self.session,
            actor=actor,
            action=AuditAction.TICKET_MAILBOX,
            target_type="ticket_area",
            target_id=str(area_id),
            data={"op": op, "fields": fields, "address": row.address, "enabled": bool(row.enabled)},
        )
