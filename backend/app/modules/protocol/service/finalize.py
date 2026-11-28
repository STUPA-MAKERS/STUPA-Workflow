"""The finalization of a protocol (start, blackout check, render, store) and its send."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, or_, select

from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.gremien.models import Gremium
from app.modules.meetings.models import Meeting, MeetingAgendaItem
from app.modules.meetings.protocol_models import Protocol
from app.modules.notifications.brand import load_mail_brand
from app.modules.notifications.compose import branded_mail
from app.modules.notifications.links import protocol_link, public_protocol_url
from app.modules.notifications.mail import MailAttachment, compute_idempotency_key
from app.modules.protocol.filename import protocol_pdf_filename
from app.modules.protocol.plan_anlage import attach_plans
from app.modules.protocol.public import meeting_day
from app.modules.protocol.schemas import ProtocolOut
from app.modules.protocol.service.common import _mark_final, _mark_sent
from app.modules.protocol.service.render import RenderOps
from app.modules.protocol.webhook_fields import emit_protocol_finalized
from app.modules.site_config.features import Feature, feature_on
from app.settings import get_settings
from app.shared.blackout import has_open_marker
from app.shared.errors import ConflictError, ServiceUnavailableError, ValidationProblem


class FinalizeOps(RenderOps):
    """Finalize a protocol, and send a final one."""

    async def start_finalize(
        self, protocol_id: UUID, *, actor: str, public_withheld: bool | None = None
    ) -> ProtocolOut:
        """Start the finalization and move the protocol from `draft` to `rendering`.

        The method commits and does not block. The caller, that is the router, then
        enqueues the `render_protocol` worker job. It writes `protocol_finalize`.

        The finalization happens once, after the close of the meeting.
        A protocol under render or a final protocol gives 409. That rule blocks a
        double render and a double send. The method locks the protocol row, so two
        parallel calls run one after the other: the second call sees `rendering`
        and gets 409.

        `public_withheld` holds back the protocol from the public protocols page
        (`True`) or releases it (`False`). `None` keeps the stored value, so a
        protocol held back as a draft stays held back. A change writes
        `protocol_publication`. The finalization renders the public version
        anyway, so a later release needs no render.

        The finalization pseudonymizes the guests ("Gast 1 … n"). The protocol carries
        them as a count only.

        Raises:
            ConflictError: The meeting is not closed (`meeting_not_closed`), or the
                protocol is not a draft (`protocol_not_draft`).
            ValidationProblem: A text has an open blackout marker (`blackout_unclosed`).
        """
        protocol = await self._get(protocol_id, for_update=True)
        meeting = await self._meeting(protocol.meeting_id)
        if meeting.status != "closed":
            raise ConflictError(
                "close the meeting before the protocol is finalized",
                code="meeting_not_closed",
            )
        if protocol.status != "draft":
            raise ConflictError(
                f"the protocol is {protocol.status} — it is finalized only once",
                code="protocol_not_draft",
            )
        await self._check_blackout(protocol)
        protocol.status = "rendering"
        old_withheld = bool(protocol.public_withheld)
        if public_withheld is not None and public_withheld != old_withheld:
            protocol.public_withheld = public_withheld
            await self._audit_publication(protocol, actor, old_withheld, public_withheld)
        from app.modules.livevote.guests import GuestService

        await GuestService(self.session).pseudonymize(protocol.meeting_id)
        await audit_record(
            self.session,
            actor=actor,
            action=AuditAction.PROTOCOL_FINALIZE,
            target_type="protocol",
            target_id=str(protocol_id),
            data={
                "meetingId": str(protocol.meeting_id),
                "gremiumId": str(protocol.gremium_id),
                "publicWithheld": bool(protocol.public_withheld),
            },
        )
        await self.session.flush()
        await self.session.commit()
        return await self._to_out(protocol)

    async def _check_blackout(self, protocol: Protocol) -> None:
        """Refuse a protocol with an open blackout marker (000686).

        Raises:
            ValidationProblem: A `%%` has no closing pair (`blackout_unclosed`). The
                detail names the TOP, or the free text.
        """
        open_at = [n for n, text in await self._texts(protocol) if has_open_marker(text)]
        if not open_at:
            return
        number = open_at[0]
        where = "the free text" if number is None else f"TOP {number}"
        raise ValidationProblem(
            f"{where} has a blackout marker %% without its closing %%",
            code="blackout_unclosed",
            errors=[{"field": "text" if number is None else f"top.{number}", "msg": where}],
        )

    async def finalize(self, protocol_id: UUID, *, now: datetime) -> ProtocolOut:
        """Render the Markdown into a PDF, store it and set the protocol to `final`.

        The finalization sends no mail (spec 003019): `send` mails the stored PDF.

        The method runs in the worker (`render_protocol`, status `rendering`). Without
        Redis it runs synchronously as a fallback, and the status is still `draft`. It
        sets the status to `final`. The method is idempotent. An already final
        protocol comes back unchanged, with no second render.

        The typst render runs BEFORE the commit. A permanent render error (4xx) or a
        short typst outage (5xx) rolls the session back, and the protocol stays draft.
        The storage `put` runs only AFTER a successful commit, because a failed commit
        would otherwise leave an orphaned MinIO object for a row that never became
        `final`.

        The method renders two PDFs when the meeting has a non-public item or the
        gremium publishes its protocols: the full internal PDF and the redacted public
        PDF. With a non-public item or a blackout mark (000691) the send mails only the
        public variant, so neither a non-public item nor a marked name reaches the list.
        A gremium that publishes its protocols always gets the public variant, for the
        public page.
        """
        protocol = await self._get(protocol_id)
        if protocol.status == "final":
            return await self._to_out(protocol)

        mail_public = await self._mails_public(protocol)
        gremium = await self.session.get(Gremium, protocol.gremium_id)
        await attach_plans(self.session, self.storage, self.typst, protocol.meeting_id, now.date())
        uploads, _ = (
            await self._render_both(protocol, mail_public=mail_public)
            if mail_public or bool(getattr(gremium, "protocols_public", False))
            else await self._render_internal(protocol)
        )
        _mark_final(protocol, now)
        await emit_protocol_finalized(self.session, protocol)
        await self.session.flush()
        await self.session.commit()
        await self._store(uploads)
        return await self._to_out(protocol)

    async def send(
        self, protocol_id: UUID, *, now: datetime, actor: str
    ) -> tuple[int, ProtocolOut]:
        """Mail the stored PDF of a final protocol to MAIL_LIST(gremium) (spec 003019).

        The mail carries the public variant when the meeting has a non-public item or
        a blackout mark (000691), else the internal one. The send sets `sent_at` and
        writes `protocol_send` with the number of recipients. A repeat is allowed: its
        idempotency key holds the time of the send. The caller commits.

        Returns:
            The number of addresses and the protocol after the send.

        Raises:
            ConflictError: The protocol is not final (`protocol_not_final`), or the
                Gremium has no recipient (`protocol_no_recipients`).
            ServiceUnavailableError: No mail queue is configured (503).
        """
        protocol = await self._get(protocol_id, for_update=True)
        if protocol.status != "final":
            raise ConflictError("Only a final protocol can be sent.", code="protocol_not_final")
        if self.mail_queue is None:
            raise ServiceUnavailableError("The protocol cannot be sent now.")
        recipients = await self._mail_recipients(protocol)
        if not recipients:
            raise ConflictError(
                "The Gremium has no recipient for the protocol.", code="protocol_no_recipients"
            )
        public = protocol.public_pdf_storage_key is not None and await self._mails_public(protocol)
        key = protocol.public_pdf_storage_key if public else protocol.pdf_storage_key
        pdf = await self._stored_pdf(key) if key is not None else None
        await self._send(protocol, pdf, recipients, at=now)
        _mark_sent(protocol, now)
        await audit_record(
            self.session,
            actor=actor,
            action=AuditAction.PROTOCOL_SEND,
            target_type="protocol",
            target_id=str(protocol_id),
            data={
                "meetingId": str(protocol.meeting_id),
                "gremiumId": str(protocol.gremium_id),
                "recipients": len(recipients),
            },
        )
        await self.session.flush()
        return len(recipients), await self._to_out(protocol)

    async def _mails_public(self, protocol: Protocol) -> bool:
        """Return True if only the public PDF may go to the mailing list.

        That is the case with a non-public agenda item, or with a `%%` in a TOP body
        or in the free text: a blackout mark (000691). The `%%` test is wider than a
        mark on purpose, because the public PDF is the safe choice. One count query
        serves both rules.
        """
        found = await self.session.scalar(
            select(func.count())
            .select_from(MeetingAgendaItem)
            .where(
                MeetingAgendaItem.meeting_id == protocol.meeting_id,
                or_(
                    MeetingAgendaItem.non_public.is_(True),
                    MeetingAgendaItem.body.contains("%%", autoescape=True),
                ),
            )
        )
        return bool(found) or "%%" in (protocol.markdown or "")

    async def _send(
        self,
        protocol: Protocol,
        pdf: bytes | None,
        to: Sequence[str] | None = None,
        *,
        at: datetime,
    ) -> None:
        """Mail the protocol to MAIL_LIST(gremium) under an idempotency key.

        `to` holds the recipients that the send already read. Without it the method
        reads them itself.

        The key holds the time of the send, so each send goes out (spec 003019).

        The mail carries the PDF as an attachment. The subject and the body name the
        Gremium and the meeting. The HTML version uses the branded mail layout.

        The mail links the meeting page, which holds the protocol: a member opens it
        after the login. An external list address cannot log in, so the PDF stays the
        content of the mail. When the protocol is public, the mail also links its
        public version, which everybody can open. The mail never links the API
        (`/api/protocols/{id}/pdf`), because that read needs a meeting management
        right.

        The public link follows the rule of `public.visible_clause`, applied to the
        protocol in hand.
        """
        if self.mail_queue is None:
            return
        recipients = to if to is not None else await self._mail_recipients(protocol)
        if not recipients:
            return
        gremium = await self.session.get(Gremium, protocol.gremium_id)
        gremium_name = gremium.name if gremium is not None else None
        meeting = await self.session.get(Meeting, protocol.meeting_id)
        day = (
            meeting.date.strftime("%d.%m.%Y")
            if meeting is not None and meeting.date is not None
            else None
        )
        subject = (
            "Sitzungsprotokoll"
            + (f" {gremium_name}" if gremium_name else "")
            + (f" — {day}" if day else "")
        )
        settings = self.settings or get_settings()
        link = protocol_link(settings, protocol.meeting_id)
        public = (
            gremium is not None
            and bool(getattr(gremium, "protocols_public", False))
            and protocol.status == "final"
            and not protocol.public_withheld
            and protocol.public_content is not None
            and await feature_on(self.session, Feature.PUBLIC)
        )
        lines = [
            *([f"Sitzung: {meeting.title}"] if meeting is not None else []),
            *([f"Gremium: {gremium_name}"] if gremium_name else []),
            *([f"Datum: {day}"] if day else []),
            *(
                ["Öffentliche Fassung: " + public_protocol_url(settings, protocol.id)]
                if public
                else []
            ),
        ]
        intro = (
            "Das Sitzungsprotokoll wurde finalisiert und liegt als PDF bei."
            if pdf is not None
            else "Das Sitzungsprotokoll wurde finalisiert."
        )
        body = intro + ("\n\n" + "\n".join(lines) if lines else "") + "\n"
        filename = (
            protocol_pdf_filename(meeting.title, meeting_day(meeting))
            if meeting is not None
            else "Protokoll.pdf"
        )
        attachments = (
            (MailAttachment(filename=filename, mime="application/pdf", content=pdf),)
            if pdf is not None
            else ()
        )
        await self.mail_queue.enqueue(
            branded_mail(
                brand=await load_mail_brand(self.session, settings),
                settings=settings,
                to=tuple(recipients),
                subject=subject,
                text=body,
                reason="protocol",
                lang="de",
                idempotency_key=compute_idempotency_key(
                    "protocol_finalized", str(protocol.id), at.isoformat()
                ),
                link=link,
                attachments=attachments,
            )
        )
