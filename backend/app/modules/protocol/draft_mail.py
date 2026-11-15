"""The draft of a protocol by mail (§F/meetings/protocols/000925).

The keeper sends the PDF of a draft to the members of the Gremium. Each page has the
watermark "Entwurf". The send changes no status, no stored PDF and no key column of the
protocol; it stores only its own time. The members get the variant that a finalization
would mail: the public one when the meeting has a non-public item or the text has a
blackout mark.

A live meeting refuses the send, because its draft is not complete, and the stored time
lets the client ask before a second send (§F/meetings/protocols/000937).

A reader of the meeting also reads the draft as a PDF without a mail (`preview`,
§F/meetings/protocols/000950): the internal variant or the public one, each with the
watermark, and only after the meeting. This read stores nothing and writes no audit entry.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import update

from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.gremien.models import Gremium
from app.modules.meetings.models import Meeting
from app.modules.meetings.protocol_models import Protocol
from app.modules.notifications.layout import (
    append_link_text,
    reason_text,
    render_layout,
    text_to_html,
)
from app.modules.notifications.links import protocol_link
from app.modules.notifications.mail import (
    MailAttachment,
    MailMessage,
    compute_idempotency_key,
)
from app.modules.notifications.recipients import RecipientResolver
from app.modules.notifications.service import filter_recipients_by_preference
from app.modules.protocol.filename import protocol_pdf_filename
from app.modules.protocol.public import meeting_day
from app.modules.protocol.service import ProtocolService
from app.settings import get_settings
from app.shared.errors import ConflictError, ServiceUnavailableError

WATERMARK = "Entwurf"
PROTOCOL_NOT_DRAFT = "protocol_not_draft"
MEETING_LIVE = "meeting_live"
_BODY = (
    "Der Entwurf des Sitzungsprotokolls liegt als PDF bei. Er ist noch nicht "
    "finalisiert. Anmerkungen gehen an die Protokollführung."
)


@dataclass(frozen=True, slots=True)
class DraftMailer:
    """Send the draft of a protocol to the members of its Gremium."""

    service: ProtocolService

    async def send(self, protocol_id: UUID, *, now: datetime, actor: str) -> int:
        """Render the draft with the watermark and mail it. Return the number of addresses.

        A send to one address or more stores `now` as the time of the last send. The
        caller commits it together with the audit entry.

        Raises:
            ConflictError: The protocol is not a draft (409 ``protocol_not_draft``), or
                its meeting is live (409 ``meeting_live``).
            ServiceUnavailableError: No render service, no storage or no mail queue is
                configured, so no PDF can go out (503).
            BadRequestError: typst refused the document (400 ``render_failed``).
        """
        svc = self.service
        protocol = await svc._get(protocol_id)
        if protocol.status != "draft":
            raise ConflictError("Only a draft can be sent as a draft.", code=PROTOCOL_NOT_DRAFT)
        meeting = await svc.session.get(Meeting, protocol.meeting_id)
        if meeting is not None and meeting.status == "live":
            raise ConflictError("The draft of a live meeting cannot be sent.", code=MEETING_LIVE)
        public = await svc._mails_public(protocol)
        markdown = await svc._build_document(protocol, public=public)
        pdf = await svc._render_pdf(protocol, markdown, public=public, watermark=WATERMARK)
        if pdf is None or svc.mail_queue is None:
            raise ServiceUnavailableError("The draft cannot be sent now.")
        members = await RecipientResolver(svc.session).resolve(
            [{"kind": "gremium", "ref": str(protocol.gremium_id)}]
        )
        recipients = await filter_recipients_by_preference(svc.session, members, "protocol")
        if recipients:
            await svc.mail_queue.enqueue(await self._message(protocol_id, recipients, pdf, now))
            await svc.session.execute(
                update(Protocol).where(Protocol.id == protocol.id).values(draft_sent_at=now)
            )
        await audit_record(
            svc.session,
            actor=actor,
            action=AuditAction.PROTOCOL_DRAFT_MAIL,
            target_type="protocol",
            target_id=str(protocol.id),
            data={
                "meetingId": str(protocol.meeting_id),
                "gremiumId": str(protocol.gremium_id),
                "recipients": len(recipients),
            },
        )
        return len(recipients)

    async def preview(self, protocol_id: UUID, *, public: bool) -> tuple[bytes, str]:
        """Render the draft with the watermark. Return the PDF and its download name.

        `public` picks the redacted variant. Nothing is stored and nothing is sent.

        Raises:
            ConflictError: The protocol is not a draft (409 ``protocol_not_draft``), or
                its meeting is live (409 ``meeting_live``).
            ServiceUnavailableError: No render service or no storage is configured (503).
            BadRequestError: typst refused the document (400 ``render_failed``).
        """
        svc = self.service
        protocol = await svc._get(protocol_id)
        if protocol.status != "draft":
            raise ConflictError("Only a draft has a draft PDF.", code=PROTOCOL_NOT_DRAFT)
        meeting = await svc.session.get(Meeting, protocol.meeting_id)
        if meeting is not None and meeting.status == "live":
            raise ConflictError("A live meeting has no draft PDF.", code=MEETING_LIVE)
        markdown = await svc._build_document(protocol, public=public)
        pdf = await svc._render_pdf(protocol, markdown, public=public, watermark=WATERMARK)
        if pdf is None:
            raise ServiceUnavailableError("The draft cannot be rendered now.")
        name = (
            protocol_pdf_filename(meeting.title, meeting_day(meeting), public=public)
            if meeting is not None
            else "Protokoll.pdf"
        )
        return pdf, f"Entwurf_{name}"

    async def last_sent(self, protocol_id: UUID) -> datetime | None:
        """Return the time of the last send before this request, or None.

        `send` writes the new time with an UPDATE, so the loaded row keeps the old one.
        """
        protocol = await self.service._get(protocol_id)
        return protocol.draft_sent_at

    async def _message(
        self, protocol_id: UUID, recipients: list[str], pdf: bytes, now: datetime
    ) -> MailMessage:
        """Build the mail: the subject names the Gremium and the day, the PDF is attached."""
        svc = self.service
        protocol = await svc._get(protocol_id)
        gremium = await svc.session.get(Gremium, protocol.gremium_id)
        meeting = await svc.session.get(Meeting, protocol.meeting_id)
        gremium_name = gremium.name if gremium is not None else None
        day = (
            meeting.date.strftime("%d.%m.%Y")
            if meeting is not None and meeting.date is not None
            else None
        )
        subject = (
            "Protokollentwurf"
            + (f" {gremium_name}" if gremium_name else "")
            + (f" — {day}" if day else "")
        )
        lines = [
            *([f"Sitzung: {meeting.title}"] if meeting is not None else []),
            *([f"Gremium: {gremium_name}"] if gremium_name else []),
            *([f"Datum: {day}"] if day else []),
        ]
        body = _BODY + ("\n\n" + "\n".join(lines) if lines else "") + "\n"
        settings = svc.settings or get_settings()
        link = protocol_link(settings, protocol.meeting_id)
        name = (
            protocol_pdf_filename(meeting.title, meeting_day(meeting))
            if meeting is not None
            else "Protokoll.pdf"
        )
        return MailMessage(
            to=tuple(recipients),
            subject=subject,
            text=append_link_text(body, link.url, link.label("de")),
            html=render_layout(
                content_html=text_to_html(body),
                title=subject,
                site_name=settings.mail_from_name,
                base_url=settings.public_base_url,
                reason=reason_text("protocol", "de"),
                lang="de",
                action_url=link.url,
                action_label=link.label("de"),
            ),
            idempotency_key=compute_idempotency_key(
                "protocol_draft", str(protocol.id), now.isoformat()
            ),
            attachments=(
                MailAttachment(filename=f"Entwurf {name}", mime="application/pdf", content=pdf),
            ),
        )
