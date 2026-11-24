"""Shared base of the protocol service ops classes: constructor, lookups, output, audit."""

from __future__ import annotations

from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.files.storage import ObjectStorage
from app.modules.gremien.models import Gremium
from app.modules.livevote.service import MeetingService
from app.modules.meetings.agenda_service import agenda_order
from app.modules.meetings.models import Meeting, MeetingAgendaItem
from app.modules.meetings.protocol_models import Protocol
from app.modules.notifications.queue import MailQueue
from app.modules.notifications.recipients import RecipientResolver
from app.modules.notifications.service import filter_recipients_by_preference
from app.modules.pdf.typst_client import TypstClient
from app.modules.protocol.approval import approval_fields
from app.modules.protocol.schemas import ProtocolOut
from app.modules.voting.models import Vote
from app.settings import Settings, get_settings
from app.shared.errors import ConflictError, NotFoundError, ValidationProblem


class ProtocolServiceBase:
    """Constructor and helpers that every ops class of ``ProtocolService`` uses."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        storage: ObjectStorage | None = None,
        typst: TypstClient | None = None,
        mail_queue: MailQueue | None = None,
        settings: Settings | None = None,
    ) -> None:
        """Bind the service to a session and its optional backends."""
        self.session = session
        self.storage = storage
        self.typst = typst
        self.mail_queue = mail_queue
        self.settings = settings

    async def _get(self, protocol_id: UUID, *, for_update: bool = False) -> Protocol:
        """Load a protocol.

        With `for_update`, the method locks the row (`SELECT … FOR UPDATE`) and
        reads the columns again, also when the session holds the row already.
        """
        base = select(Protocol).where(Protocol.id == protocol_id)
        stmt = (
            base.with_for_update().execution_options(populate_existing=True) if for_update else base
        )
        protocol = (await self.session.execute(stmt)).scalar_one_or_none()
        if protocol is None:
            raise NotFoundError(f"protocol {protocol_id} not found")
        return protocol

    def _meeting_service(self) -> MeetingService:
        """Return the meeting service that authorizes the per-item bodies.

        The live stack authorizes the per-item bodies per gremium: the assigned
        protokollant plus the gremium roles with `session.manage` or `protocol.write`.
        The protocol assembles these bodies, so it delegates to `MeetingService` and
        applies the same scope rules as `/api/meetings/…`.
        """
        return MeetingService(self.session)

    async def _meeting(self, meeting_id: UUID) -> Meeting:
        meeting = await self.session.get(Meeting, meeting_id)
        if meeting is None:
            raise NotFoundError(f"meeting {meeting_id} not found")
        return meeting

    def _pdf_path(self, protocol: Protocol) -> str | None:
        """Build the app-relative PDF path, never a bucket link.

        The browser reaches the path through nginx under `/api/`. MinIO sits on the
        internal network without a published port. An S3v4-signed URL binds the
        internal host into the signature, so the browser cannot reach it. The `/pdf`
        endpoint streams the bytes server-side.

        Returns:
            The path, or `None` when no PDF exists or storage is off.
        """
        stored = protocol.pdf_storage_key is not None and self.storage is not None
        return f"/api/protocols/{protocol.id}/pdf" if stored else None

    def _public_pdf_path(self, protocol: Protocol) -> str | None:
        """Build the app-relative path of the redacted public variant."""
        stored = protocol.public_pdf_storage_key is not None and self.storage is not None
        return f"/api/protocols/{protocol.id}/pdf/public" if stored else None

    async def _to_out(self, protocol: Protocol) -> ProtocolOut:
        gremium = await self.session.get(Gremium, protocol.gremium_id)
        return ProtocolOut(
            id=protocol.id,
            meetingId=protocol.meeting_id,
            markdown=protocol.markdown,
            status=protocol.status,  # type: ignore[arg-type]
            pdfUrl=self._pdf_path(protocol),
            publicPdfUrl=self._public_pdf_path(protocol),
            sentAt=protocol.sent_at,
            publicWithheld=bool(getattr(protocol, "public_withheld", False)),
            gremiumProtocolsPublic=bool(getattr(gremium, "protocols_public", False)),
            draftSentAt=getattr(protocol, "draft_sent_at", None),
            **await approval_fields(self.session, protocol),
        )

    async def _by_meeting(self, meeting_id: UUID) -> Protocol | None:
        return (
            await self.session.execute(select(Protocol).where(Protocol.meeting_id == meeting_id))
        ).scalar_one_or_none()

    @staticmethod
    def _insert_values(
        meeting: Meeting, cd_variant: str | None, author: str | None
    ) -> dict[str, object]:
        """Build the column values of a new `protocol` row.

        `cd_variant` is the key of the CD variant of the Gremium. The protocol
        snapshots it, so a later change of the Gremium does not rewrite the
        design of a protocol that already exists.
        """
        return {
            "meeting_id": meeting.id,
            "gremium_id": meeting.gremium_id,
            "markdown": "",
            "status": "draft",
            "author": author,
            "cd_variant": cd_variant,
        }

    async def _audit_publication(
        self, protocol: Protocol, actor: str, old: bool, new: bool
    ) -> None:
        """Write `protocol_publication` with the old and the new hold-back value."""
        await audit_record(
            self.session,
            actor=actor,
            action=AuditAction.PROTOCOL_PUBLICATION,
            target_type="protocol",
            target_id=str(protocol.id),
            data={
                "meetingId": str(protocol.meeting_id),
                "gremiumId": str(protocol.gremium_id),
                "old": old,
                "new": new,
            },
        )

    def _tz(self) -> ZoneInfo:
        settings = self.settings or get_settings()
        return ZoneInfo(settings.local_timezone)

    async def _texts(self, protocol: Protocol) -> list[tuple[int | None, str]]:
        """Return the Markdown texts: the TOP bodies with their numbers, then the free text."""
        bodies = (
            (
                await self.session.execute(
                    select(MeetingAgendaItem.body)
                    .where(MeetingAgendaItem.meeting_id == protocol.meeting_id)
                    .order_by(*agenda_order())
                )
            )
            .scalars()
            .all()
        )
        tops = [(number, body) for number, body in enumerate(bodies, start=1) if body]
        return [*tops, *([(None, protocol.markdown)] if protocol.markdown else [])]

    async def _recipients(self, gremium_id: UUID) -> list[str]:
        """Build the flat and deduplicated recipient list of the Gremium.

        The list is the union of the Gremium members and the extra addresses of
        the Gremium (`gremium.protocol_recipients`). A member counts with a
        non-NULL email. The extra addresses get the protocol in addition to the
        members, not instead of them.
        """
        members = await RecipientResolver(self.session).resolve(
            [{"kind": "gremium", "ref": str(gremium_id)}]
        )
        gremium = await self.session.get(Gremium, gremium_id)
        extra = gremium.protocol_recipients if gremium is not None else None
        return list(dict.fromkeys([*members, *(extra or [])]))

    async def _mail_recipients(self, protocol: Protocol) -> list[str]:
        """Return the addresses that get the mail of the final protocol.

        The list is empty without a mail queue and for a Gremium without a recipient.
        The finalization then sets no `sent_at`, so the page does not say that the
        protocol was sent.
        """
        if self.mail_queue is None:
            return []
        members = await self._recipients(protocol.gremium_id)
        return list(await filter_recipients_by_preference(self.session, members, "protocol"))

    @staticmethod
    def _ensure_draft(protocol: Protocol) -> None:
        """Require an editable draft protocol.

        A protocol under render is read-only too, because its content is frozen during
        the background render and the PDF would otherwise show a different state than
        the editor.

        Raises:
            ConflictError: The protocol is final or under render.
        """
        if protocol.status == "final":
            raise ConflictError("Protocol is finalized and read-only.", code="protocol_finalized")
        if protocol.status == "rendering":
            raise ConflictError(
                "Protocol is being rendered and is read-only.", code="protocol_rendering"
            )

    async def _get_vote(self, vote_id: UUID, *, meeting_id: UUID) -> Vote:
        """Load a vote of the meeting of the protocol.

        Raises:
            NotFoundError: The vote does not exist.
            ValidationProblem: The vote belongs to another meeting or to none
                (`vote_not_in_meeting`).
        """
        vote = await self.session.get(Vote, vote_id)
        if vote is None:
            raise NotFoundError(f"vote {vote_id} not found")
        if vote.meeting_id != meeting_id:
            raise ValidationProblem(
                f"vote {vote_id} does not belong to the meeting of this protocol",
                code="vote_not_in_meeting",
            )
        return vote
