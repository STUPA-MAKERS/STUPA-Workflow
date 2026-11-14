"""The draft of a protocol by mail (§F/meetings/protocols/000925).

The keeper sends the PDF of a draft to the members of the Gremium. Each page has the
watermark "Entwurf". The send changes nothing on the protocol: no status, no stored PDF
and no key column. The members get the variant that a finalization would mail: the
public one when the meeting has a non-public item or the text has a blackout mark.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.gremien.models import Gremium
from app.modules.meetings.models import Meeting
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
from app.shared.errors import ServiceUnavailableError

WATERMARK = "Entwurf"
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

        The caller commits the audit entry.

        Raises:
            ConflictError: The protocol is not a draft (409 ``protocol_not_draft``).
            ServiceUnavailableError: No render service, no storage or no mail queue is
                configured, so no PDF can go out (503).
            BadRequestError: typst refused the document (400 ``render_failed``).
        """
        svc = self.service
        protocol = await svc._get(protocol_id)
        svc._ensure_draft(protocol)
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
