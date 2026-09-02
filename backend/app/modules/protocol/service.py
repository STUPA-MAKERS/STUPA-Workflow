"""Protocol service.

The service binds to an `AsyncSession` and drives the protocol lifecycle.

* `get_or_create` creates or loads the protocol of a meeting. It is idempotent
  through the UNIQUE `meeting_id`. It takes `gremium_id` and `cd_variant` from
  the meeting and the Gremium.
* `update_markdown` updates the editor body. It accepts a draft only.
* `embed_votes` appends votes as Markdown snippets and writes
  `protocol_vote_ref`. It is idempotent and skips an already referenced vote.
* `finalize` renders the Markdown through pytex into a PDF. It stores the PDF
  in MinIO and mails it to MAIL_LIST(gremium). It sets `status='final'` and
  `sent_at`.

The service reuses the pytex client, the object storage and the mail queue of
`app.modules.pdf` and `app.modules.notifications` without a change.

Failure discipline: if storage is off by design (dev or demo without MinIO),
`finalize` still completes. The protocol becomes `final` and the mail goes out
without a PDF link. If an EXISTING render or storage backend fails for a short
time, the service raises `ServiceUnavailableError` (503). The session dependency
then rolls back, the protocol stays draft and the caller can repeat the call.
"""

from __future__ import annotations

from datetime import UTC, datetime
from datetime import time as _time
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.cd_resolver import (
    cd_render_config,
    cd_variant_key_for_gremium,
    resolve_cd_variant_by_key,
)
from app.modules.admin.gremium_roles import gremium_ids_with_permission
from app.modules.admin.models import Gremium, GremiumMembership, MailList
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.files.storage import ObjectStorage, StorageError
from app.modules.livevote.models import Meeting, MeetingAgendaItem, MeetingAttendance
from app.modules.livevote.service import MeetingService
from app.modules.notifications.layout import (
    reason_text,
    render_layout,
    text_to_html,
)
from app.modules.notifications.mail import (
    MailAttachment,
    MailMessage,
    compute_idempotency_key,
)
from app.modules.notifications.queue import MailQueue
from app.modules.notifications.recipients import RecipientResolver
from app.modules.notifications.service import filter_recipients_by_preference
from app.modules.pdf.pytex_client import PytexClient, PytexError
from app.modules.protocol.markdown import (
    ProtocolDoc,
    build_protocol_document,
    build_vote_snippet,
    demote_headings,
    protocol_variant_for,
)
from app.modules.protocol.models import Protocol, ProtocolVoteRef
from app.modules.protocol.schemas import ProtocolOut
from app.modules.voting.models import Vote
from app.modules.voting.service import VotingService
from app.settings import Settings, get_settings
from app.shared.errors import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
)


def protocol_storage_key(protocol_id: UUID) -> str:
    """Build the deterministic MinIO key under the own `pdf/protocol/` prefix."""
    return f"pdf/protocol/{protocol_id}.pdf"


def protocol_public_storage_key(protocol_id: UUID) -> str:
    """Build the MinIO key of the redacted public protocol variant."""
    return f"pdf/protocol/{protocol_id}-public.pdf"


# Placeholder for the body of a non-public agenda item in the public PDF. The
# numbering stays and the content is redacted.
_NON_PUBLIC_PLACEHOLDER = "*(nicht-öffentlicher Tagesordnungspunkt)*"
# Neutral heading for a non-public item in the public PDF. The original title can
# encode the sensitive subject and must not reach the mailed variant.
_NON_PUBLIC_HEADING = "Nicht-öffentlicher Tagesordnungspunkt"


class ProtocolService:
    """Run the protocol operations and the finalization over the shared render stack."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        storage: ObjectStorage | None = None,
        pytex: PytexClient | None = None,
        mail_queue: MailQueue | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.storage = storage
        self.pytex = pytex
        self.mail_queue = mail_queue
        self.settings = settings

    async def _get(self, protocol_id: UUID) -> Protocol:
        protocol = (
            await self.session.execute(
                select(Protocol).where(Protocol.id == protocol_id)
            )
        ).scalar_one_or_none()
        if protocol is None:
            raise NotFoundError(f"protocol {protocol_id} not found")
        return protocol

    # The protocol assembles the per-item bodies. The live stack already authorizes
    # these bodies PER GREMIUM: the assigned protokollant plus the Gremium roles with
    # `session.manage` or `protocol.write`. A global `meeting.manage` alone would lock
    # those users out. The service therefore delegates to `MeetingService` and applies
    # the same scope rules as `/api/meetings/…`.
    def _meeting_service(self) -> MeetingService:
        return MeetingService(self.session)

    async def _meeting(self, meeting_id: UUID) -> Meeting:
        meeting = await self.session.get(Meeting, meeting_id)
        if meeting is None:
            raise NotFoundError(f"meeting {meeting_id} not found")
        return meeting

    async def authorize_write_meeting(
        self, meeting_id: UUID, principal: Principal
    ) -> None:
        """Check the write access to the protocol of a meeting (create or load).

        One of these rights is enough: the manager permission `meeting.manage`, the
        Gremium permission `session.manage`, the assigned protokollant role, or a
        Gremium role with `protocol.write`. The rule is the same as `can_write`.

        Raises:
            ForbiddenError: The principal must not write the minutes of this meeting.
        """
        meeting = await self._meeting(meeting_id)
        if not await self._meeting_service().can_write(meeting, principal):
            raise ForbiddenError("not allowed to write this meeting's minutes")

    async def authorize_write(self, protocol_id: UUID, principal: Principal) -> None:
        """Check the write access to an existing protocol (PATCH or embed votes)."""
        protocol = await self._get(protocol_id)
        await self.authorize_write_meeting(protocol.meeting_id, principal)

    async def authorize_finalize(self, protocol_id: UUID, principal: Principal) -> None:
        """Check the right to finalize and send a protocol.

        The caller needs the write access AND `protocol.finalize`. The permission
        counts as a global permission OR as a Gremium role of this Gremium. This rule
        is stricter than the rule for a draft write.

        Raises:
            ForbiddenError: The caller has no write access or lacks
                `protocol.finalize`.
        """
        protocol = await self._get(protocol_id)
        meeting = await self._meeting(protocol.meeting_id)
        svc = self._meeting_service()
        if not await svc.can_write(meeting, principal):
            raise ForbiddenError("not allowed to write this meeting's minutes")
        if principal.has("protocol.finalize"):
            return
        if meeting.gremium_id in await gremium_ids_with_permission(
            self.session, principal.sub, "protocol.finalize"
        ):
            return
        raise ForbiddenError("Missing permission(s): protocol.finalize")

    async def authorize_read(self, protocol_id: UUID, principal: Principal) -> None:
        """Check the read access with the meeting visibility rule `assert_can_read`."""
        protocol = await self._get(protocol_id)
        await self._meeting_service().assert_can_read(protocol.meeting_id, principal)

    async def authorize_read_meeting(
        self, meeting_id: UUID, principal: Principal
    ) -> None:
        """Check the read access to the protocol of a meeting (GET …/protocol)."""
        await self._meeting_service().assert_can_read(meeting_id, principal)

    def _pdf_path(self, protocol: Protocol) -> str | None:
        """Build the app-relative PDF path, never a bucket link.

        The browser reaches the path through nginx under `/api/`. MinIO sits on the
        internal network without a published port. An S3v4-signed URL binds the
        internal host into the signature, so the browser cannot reach it. The `/pdf`
        endpoint streams the bytes server-side.

        Returns:
            The path, or `None` when no PDF exists or storage is off.
        """
        if protocol.pdf_storage_key is not None and self.storage is not None:
            return f"/api/protocols/{protocol.id}/pdf"
        return None

    def _public_pdf_path(self, protocol: Protocol) -> str | None:
        """Build the app-relative path of the redacted public variant."""
        if protocol.public_pdf_storage_key is not None and self.storage is not None:
            return f"/api/protocols/{protocol.id}/pdf/public"
        return None

    async def get_pdf_bytes(self, protocol_id: UUID) -> bytes:
        """Fetch the PDF bytes of the protocol from storage for the `/pdf` stream.

        Raises:
            NotFoundError: The protocol is missing, no PDF is rendered yet, or
                storage is off (404).
            ServiceUnavailableError: The storage failed for a short time (503). The
                caller can repeat the call.
        """
        protocol = await self._get(protocol_id)
        if protocol.pdf_storage_key is None or self.storage is None:
            raise NotFoundError(f"protocol {protocol_id} has no PDF")
        try:
            return await self.storage.get(protocol.pdf_storage_key)
        except StorageError as exc:
            raise ServiceUnavailableError(
                "Protocol PDF temporarily unavailable."
            ) from exc

    async def get_public_pdf_bytes(self, protocol_id: UUID) -> bytes:
        """Fetch the bytes of the redacted public variant for the `/pdf/public` stream."""
        protocol = await self._get(protocol_id)
        if protocol.public_pdf_storage_key is None or self.storage is None:
            raise NotFoundError(f"protocol {protocol_id} has no public PDF")
        try:
            return await self.storage.get(protocol.public_pdf_storage_key)
        except StorageError as exc:
            raise ServiceUnavailableError(
                "Protocol PDF temporarily unavailable."
            ) from exc

    def _to_out(self, protocol: Protocol) -> ProtocolOut:
        return ProtocolOut(
            id=protocol.id,
            meetingId=protocol.meeting_id,
            markdown=protocol.markdown,
            status=protocol.status,  # type: ignore[arg-type]
            pdfUrl=self._pdf_path(protocol),
            publicPdfUrl=self._public_pdf_path(protocol),
            sentAt=protocol.sent_at,
        )

    async def _by_meeting(self, meeting_id: UUID) -> Protocol | None:
        return (
            await self.session.execute(
                select(Protocol).where(Protocol.meeting_id == meeting_id)
            )
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

    async def get_by_meeting(self, meeting_id: UUID) -> ProtocolOut:
        """Read the protocol of a meeting on the reload and poll path.

        This method has no create side effect, by design. The frontend polls during
        the background render. A GET is not subject to the write rate limit.

        Raises:
            NotFoundError: The meeting has no protocol (404).
        """
        protocol = await self._by_meeting(meeting_id)
        if protocol is None:
            raise NotFoundError(f"protocol for meeting {meeting_id} not found")
        return self._to_out(protocol)

    async def get_or_create(
        self, meeting_id: UUID, *, author: str | None = None
    ) -> ProtocolOut:
        """Create or load the protocol of a meeting (idempotent).

        The method is race-safe. On a parallel POST, `INSERT … ON CONFLICT
        (meeting_id) DO NOTHING` avoids the UNIQUE violation, so there is no
        `IntegrityError` and no 500. The re-select after the insert returns the same
        row in BOTH cases: created here, or won by the parallel request.

        Raises:
            NotFoundError: The meeting does not exist (404).
            ConflictError: The meeting has not started yet.
        """
        existing = await self._by_meeting(meeting_id)
        if existing is not None:
            return self._to_out(existing)

        meeting = await self.session.get(Meeting, meeting_id)
        if meeting is None:
            raise NotFoundError(f"meeting {meeting_id} not found")
        # The protocol appears only when the meeting starts (planned to live). A user
        # must never create the minutes by hand in advance.
        if meeting.status == "planned":
            raise ConflictError(
                "the meeting has not started — its minutes are created on start"
            )
        gremium = await self.session.get(Gremium, meeting.gremium_id)
        cd_variant = await cd_variant_key_for_gremium(self.session, gremium)
        await self.session.execute(
            pg_insert(Protocol)
            .values(**self._insert_values(meeting, cd_variant, author))
            .on_conflict_do_nothing(constraint="uq_protocol_meeting")
        )
        await self.session.commit()

        protocol = await self._by_meeting(meeting_id)
        if protocol is None:  # only if the row disappeared between insert and select
            raise NotFoundError(f"protocol for meeting {meeting_id} not found")
        return self._to_out(protocol)

    async def update_markdown(self, protocol_id: UUID, markdown: str) -> ProtocolOut:
        """Update the editor body.

        Raises:
            ConflictError: The protocol is final or under render (409).
        """
        protocol = await self._get(protocol_id)
        self._ensure_draft(protocol)
        protocol.markdown = markdown
        await self.session.flush()
        await self.session.commit()
        return self._to_out(protocol)

    async def delete_protocol(self, protocol_id: UUID, *, actor: str) -> None:
        """Delete a protocol while it is still a draft.

        The draft gate is the whole guard. A `final` protocol is a signed
        record that went out to the Gremium by mail, and a `rendering`
        protocol is frozen while the worker builds the PDF. Both answer 409,
        exactly as `update_markdown` does.

        Permission: the same `authorize_write` scope that the PATCH already
        enforces, and NOT `protocol.finalize`. `protocol.finalize` gates
        publishing, a different axis: it decides who may turn a draft into a
        signed record and mail it out. Discarding a draft is the opposite
        direction and touches nothing that ever left the platform. The holder
        of the write scope can already empty the body with
        `PATCH markdown=""`, so a stricter gate here would protect nothing and
        would only strand a draft that the protokollant wants to restart.

        The `protocol_vote_ref` rows cascade on the foreign key. The audit log
        records the removal, because the draft text itself is not recoverable.

        Raises:
            NotFoundError: No protocol has this id (404).
            ConflictError: The protocol is final or under render (409).
        """
        protocol = await self._get(protocol_id)
        self._ensure_draft(protocol)
        await audit_record(
            self.session,
            actor=actor,
            action=AuditAction.PROTOCOL_DELETE,
            target_type="protocol",
            target_id=str(protocol_id),
            data={
                "meetingId": str(protocol.meeting_id),
                "gremiumId": str(protocol.gremium_id),
            },
        )
        await self.session.delete(protocol)
        await self.session.commit()

    async def embed_votes(
        self, protocol_id: UUID, vote_ids: list[UUID]
    ) -> ProtocolOut:
        """Append votes as snippets and write `protocol_vote_ref` (idempotent)."""
        protocol = await self._get(protocol_id)
        self._ensure_draft(protocol)
        already = set(
            (
                await self.session.execute(
                    select(ProtocolVoteRef.vote_id).where(
                        ProtocolVoteRef.protocol_id == protocol_id
                    )
                )
            )
            .scalars()
            .all()
        )
        voting = VotingService(self.session)
        snippets: list[str] = []
        for vote_id in vote_ids:
            if vote_id in already:
                continue  # already embedded, so no duplicate snippet
            await self._get_vote(vote_id)  # 404 and avoids an FK IntegrityError
            already.add(vote_id)
            # Race-safe through ON CONFLICT (protocol_id, vote_id) DO NOTHING. If a
            # parallel request wrote the ref first, RETURNING gives nothing. There is
            # no duplicate snippet, no IntegrityError and no 500.
            inserted = (
                await self.session.execute(
                    pg_insert(ProtocolVoteRef)
                    .values(protocol_id=protocol_id, vote_id=vote_id)
                    .on_conflict_do_nothing(constraint="uq_protocol_vote_ref")
                    .returning(ProtocolVoteRef.id)
                )
            ).first()
            if inserted is None:
                continue  # a parallel request embedded the vote already
            view = await voting.get(vote_id)
            snippets.append(
                build_vote_snippet(
                    _vote_title(view.application_id, view.question),
                    view.tally.counts,
                    question=view.question,
                )
            )

        if snippets:
            body = protocol.markdown.rstrip("\n")
            joined = "\n\n".join(snippets)
            protocol.markdown = f"{body}\n\n{joined}\n" if body else f"{joined}\n"
            await self.session.flush()
        await self.session.commit()
        return self._to_out(protocol)

    async def start_finalize(self, protocol_id: UUID) -> tuple[ProtocolOut, bool]:
        """Start the finalization and move the protocol from `draft` to `rendering`.

        The method commits and does not block. The caller, that is the router, then
        enqueues the `render_protocol` worker job. The method is idempotent. A
        protocol that is already `rendering` or `final` comes back unchanged.

        Returns:
            The protocol and a flag. The flag is `False` when the caller must not
            enqueue the job. This rule blocks a double render and a double send.
        """
        protocol = await self._get(protocol_id)
        if protocol.status in ("rendering", "final"):
            return self._to_out(protocol), False
        protocol.status = "rendering"
        await self.session.flush()
        await self.session.commit()
        return self._to_out(protocol), True

    async def revert_to_draft(self, protocol_id: UUID) -> None:
        """Roll a protocol back from `rendering` to `draft`.

        Call this method after a permanent render or send failure. The protocol stays
        finalizable and never hangs in the `rendering` state. A protocol that is
        already final stays untouched.
        """
        protocol = await self._get(protocol_id)
        if protocol.status == "rendering":
            protocol.status = "draft"
            await self.session.flush()
            await self.session.commit()

    async def finalize(self, protocol_id: UUID, *, now: datetime) -> ProtocolOut:
        """Render the Markdown into a PDF, store it and mail it to MAIL_LIST(gremium).

        The method runs in the worker (`render_protocol`, status `rendering`). Without
        Redis it runs synchronously as a fallback, and the status is still `draft`. It
        sets the status to `final`. The method is idempotent. An already final
        protocol comes back unchanged, with no second render and no double send.
        """
        protocol = await self._get(protocol_id)
        if protocol.status == "final":
            return self._to_out(protocol)

        # The pytex render runs BEFORE the commit. A permanent compile error (4xx) or
        # a short pytex outage (5xx) rolls the session back and the protocol stays
        # draft. The storage `put` and the mail enqueue run only AFTER a successful
        # commit, by design. A failed commit would otherwise leave an orphaned MinIO
        # object and an enqueued send job for a row that never became `final`.
        # `_render_pdf` only sets the key columns and returns the bytes. The upload
        # runs after the commit in `_store`.
        uploads: list[tuple[str, bytes]] = []
        if await self._has_non_public(protocol.meeting_id):
            # Dual render: the full internal PDF and the redacted public PDF. The
            # service mails only the public variant. A non-public item must never
            # reach the list.
            internal_md = await self._build_document(protocol, public=False)
            internal_pdf = await self._render_pdf(protocol, internal_md, public=False)
            public_md = await self._build_document(protocol, public=True)
            public_pdf = await self._render_pdf(protocol, public_md, public=True)
            if internal_pdf is not None:
                uploads.append((protocol_storage_key(protocol.id), internal_pdf))
            if public_pdf is not None:
                uploads.append((protocol_public_storage_key(protocol.id), public_pdf))
            mail_pdf = public_pdf
        else:
            markdown = await self._build_document(protocol)
            mail_pdf = await self._render_pdf(protocol, markdown)
            if mail_pdf is not None:
                uploads.append((protocol_storage_key(protocol.id), mail_pdf))
        protocol.status = "final"
        protocol.sent_at = now
        await self.session.flush()
        await self.session.commit()
        # From here the DB state is persistent, so the side effects are safe.
        await self._store(uploads)
        await self._send(protocol, mail_pdf)
        return self._to_out(protocol)

    async def _build_document(self, protocol: Protocol, *, public: bool = False) -> str:
        meeting = await self.session.get(Meeting, protocol.meeting_id)
        gremium = await self.session.get(Gremium, protocol.gremium_id)
        title = meeting.title if meeting is not None else "Protokoll"
        # The source of truth is the per-item editor, that is the agenda. If items
        # exist, the service assembles the protocol from their Markdown bodies and the
        # decision snippets. If not, it falls back to the free text in
        # `protocol.markdown`. `public=True` redacts a non-public item.
        assembled = await self._assemble_from_agenda(protocol.meeting_id, public=public)
        # `public=True` also redacts the header metadata. The mailed variant must not
        # carry the names of the attendees, of the absentees or of the protokollant.
        # `_header_meta` then returns empty name lists and the counters only, as data
        # lines. The quorum statement rests on the counters and stays meaningful.
        protokollant, present, absent, present_count, datalines = await self._header_meta(
            meeting, public=public
        )
        return build_protocol_document(
            ProtocolDoc(
                title=title,
                gremium_name=getattr(gremium, "name", None) if gremium is not None else None,
                cd_variant=protocol.cd_variant,
                date=meeting.date if meeting is not None else None,
                start_time=getattr(meeting, "start_time", None) if meeting is not None else None,
                end_time=self._local_end_time(
                    getattr(meeting, "closed_at", None) if meeting is not None else None
                ),
                protokollant=protokollant,
                present=present,
                absent=absent,
                datalines=datalines,
                quorate=await self._quorate(gremium, present_count),
                markdown=assembled or protocol.markdown,
            )
        )

    def _local_end_time(self, closed_at: object) -> _time | None:
        """Convert `meeting.closed_at` from UTC to local time for the end line."""
        if not isinstance(closed_at, datetime):
            return None
        settings = self.settings or get_settings()
        tz = ZoneInfo(settings.local_timezone)
        return closed_at.astimezone(tz).time().replace(second=0, microsecond=0)

    async def _quorate(self, gremium: object | None, present_count: int) -> bool | None:
        """Compute the quorum from the attendees and the active members.

        The threshold is `gremium.quorum_percent` when that value is set. If not, the
        threshold is more than half of the members.

        Returns:
            The quorum result, or `None` when the Gremium or its members are missing.
            The PDF then shows no quorum statement.
        """
        gremium_id = getattr(gremium, "id", None)
        if gremium_id is None:
            return None
        now = datetime.now(UTC)
        members = (
            await self.session.scalar(
                select(func.count(func.distinct(GremiumMembership.principal_id))).where(
                    GremiumMembership.gremium_id == gremium_id,
                    (GremiumMembership.valid_from.is_(None))
                    | (GremiumMembership.valid_from <= now),
                    (GremiumMembership.valid_until.is_(None))
                    | (GremiumMembership.valid_until > now),
                )
            )
        ) or 0
        if members == 0:
            return None
        percent = getattr(gremium, "quorum_percent", None)
        if percent is not None:
            return present_count * 100 >= percent * members
        return present_count * 2 > members

    async def _header_meta(
        self, meeting: Meeting | None, *, public: bool = False
    ) -> tuple[str | None, list[str], list[str], int, list[str]]:
        """Resolve the protokollant and the attendance lists for the header.

        A list entry holds the display name of the principal, or the sub as a
        fallback. `public=True` redacts the person-related header metadata for the
        mailed variant. The full attendance lists and the name of the protokollant
        must never go external. The method then emits the counters only, as the data
        lines `Anwesend: n` and `Abwesend: n`.

        Returns:
            The tuple `(protokollant, present, absent, present_count, datalines)`.
            `present_count` holds the true number of attendees and feeds the quorum,
            even when `public=True` suppresses the name lists.
        """
        if meeting is None:
            return None, [], [], 0, []
        protokollant: str | None = None
        if getattr(meeting, "protokollant_id", None) is not None:
            protokollant = await self.session.scalar(
                select(PrincipalRow.display_name).where(
                    PrincipalRow.id == meeting.protokollant_id
                )
            )
        rows = (
            await self.session.execute(
                select(
                    MeetingAttendance.status, PrincipalRow.display_name, PrincipalRow.sub
                )
                .join(PrincipalRow, PrincipalRow.id == MeetingAttendance.principal_id)
                .where(MeetingAttendance.meeting_id == meeting.id)
                .order_by(PrincipalRow.display_name)
            )
        ).all()
        present = [name or sub for status, name, sub in rows if status == "present"]
        absent = [name or sub for status, name, sub in rows if status == "absent"]
        present_count = len(present)
        if public:
            datalines = [
                f"Anwesend: {present_count}",
                f"Abwesend: {len(absent)}",
            ]
            return None, [], [], present_count, datalines
        return protokollant, present, absent, present_count, []

    async def _has_non_public(self, meeting_id: UUID) -> bool:
        """Return True if the meeting has a non-public agenda item.

        The result drives the dual render.
        """
        return bool(
            await self.session.scalar(
                select(func.count())
                .select_from(MeetingAgendaItem)
                .where(
                    MeetingAgendaItem.meeting_id == meeting_id,
                    MeetingAgendaItem.non_public.is_(True),
                )
            )
        )

    async def _assemble_from_agenda(
        self, meeting_id: UUID, *, public: bool = False
    ) -> str:
        """Build the protocol Markdown from the agenda item bodies and their votes.

        `public=True` redacts a non-public item. The heading stays, and so does the
        numbering. A placeholder replaces the body and the decision snippets.
        """
        items = (
            await self.session.execute(
                select(MeetingAgendaItem)
                .where(MeetingAgendaItem.meeting_id == meeting_id)
                .order_by(MeetingAgendaItem.position)
            )
        ).scalars().all()
        if not items:
            return ""
        voting = VotingService(self.session)
        blocks: list[str] = []
        for item in items:
            heading = (item.title or "Tagesordnungspunkt").strip()
            # Use a top-level `#` WITHOUT a "TOP n:" prefix. The pytex service numbers
            # the sections itself as "TOP 1", "TOP 2" and so on. A `##` would get the
            # number "TOP 0.1", and a manual prefix would appear twice.
            if public and item.non_public:
                # The original title can encode the sensitive subject and must never
                # reach the mailed public variant. Use a neutral heading and redacted
                # content. The numbering stays stable.
                block = [f"# {_NON_PUBLIC_HEADING}", _NON_PUBLIC_PLACEHOLDER]
                blocks.append("\n\n".join(block))
                continue
            block = [f"# {heading}"]
            if item.body and item.body.strip():
                # Demote the body headings by one level. Only the item heading stays
                # top-level. Otherwise every `#` counts as its own agenda item.
                block.append(demote_headings(item.body.strip()))
            votes = (
                await self.session.execute(
                    select(Vote)
                    .where(
                        Vote.agenda_item_id == item.id,
                        # A canceled vote has no result and no empty tally box.
                        Vote.status != "cancelled",
                    )
                    .order_by(Vote.created_at)
                )
            ).scalars().all()
            for vote in votes:
                view = await voting.get(vote.id)
                block.append(
                    build_vote_snippet(
                        view.question or "Beschlussfrage",
                        view.tally.counts,
                        question=view.question,
                    )
                )
            blocks.append("\n\n".join(block))
        return "\n\n".join(blocks) + "\n"

    async def _render_pdf(
        self, protocol: Protocol, markdown: str, *, public: bool = False
    ) -> bytes | None:
        """Render the Markdown with pytex and return the PDF bytes.

        The render runs BEFORE the commit. The method sets the key column but does
        NOT upload. The storage `put` runs after the commit in `_store`.
        `public=True` sets `public_pdf_storage_key` instead of `pdf_storage_key`.

        Returns:
            The PDF bytes, or `None` when storage is off (dev). The method then
            renders nothing.

        Raises:
            BadRequestError: pytex reported a permanent error (400).
            ServiceUnavailableError: pytex failed for a short time (503). The draft
                survives.
        """
        # Storage is the on/off switch, by design. Without it, finalize continues
        # without a PDF (demo or contract CI without MinIO).
        if self.storage is None or self.pytex is None:
            return None
        try:
            # The protocol snapshots the CD key of its Gremium at creation, so it
            # keeps its design even after the Gremium moves to another one.
            cd = await resolve_cd_variant_by_key(
                self.session, self.storage, protocol.cd_variant
            )
            # A protocol always renders as a protocol. The design contributes logos, it
            # does not pick the document shape: `cd.base_variant` here rendered the
            # protocol of a report-based design as a report, without the TOP numbering,
            # the vote boxes and the signature page.
            variant = protocol_variant_for(protocol.cd_variant)
            config = cd_render_config(cd) if cd else None
            assets = cd.assets if cd else None
            # RCE protection: the user-written body can carry the Markdown `eval`
            # escape of pytex (`[//]: # "EXPR"` runs eval in the container).
            # `sanitize_user_markdown` removes that escape UNCONDITIONALLY during the
            # assembly in `build_protocol_document`, before the Markdown reaches
            # pytex. The `\write18` shell escape does not apply under tectonic. This
            # path therefore renders as `trusted`, the client default. The
            # protocol variant needs the template machinery of pytex, and `untrusted`
            # or `sandboxed` blocks that machinery. An untrusted render failed every
            # protocol render with 400. As a second and independent line of defense,
            # `PytexClient.render_pdf` checks the structure before the trusted render
            # and proves that no eval trigger survived. A bypass of the sanitizer then
            # becomes a contained error instead of an RCE.
            pdf = await self.pytex.render_pdf(
                markdown, variant=variant, config=config, assets=assets
            )
        except PytexError as exc:
            # A 4xx is a permanent input or compile error, for example invalid LaTeX.
            # Do not retry it. Show the scrubbed reason instead of a misleading 503. A
            # 5xx or a transport error stays transient.
            if not exc.retryable:
                raise BadRequestError(
                    f"Protocol could not be rendered: {exc}", code="render_failed"
                ) from exc
            raise ServiceUnavailableError(
                "Protocol rendering temporarily unavailable."
            ) from exc
        key = (
            protocol_public_storage_key(protocol.id)
            if public
            else protocol_storage_key(protocol.id)
        )
        if public:
            protocol.public_pdf_storage_key = key
        else:
            protocol.pdf_storage_key = key
        return pdf

    async def _store(self, uploads: list[tuple[str, bytes]]) -> None:
        """Upload the rendered PDFs to object storage AFTER a successful commit.

        The MinIO object appears only now, so a failed commit leaves no orphaned
        object. With storage off, `uploads` is empty because `_render_pdf` returned
        `None`.

        Raises:
            ServiceUnavailableError: The storage failed for a short time (503). The
                protocol is already committed as `final`. A repeated `finalize` is a
                no-op through the `status=='final'` idempotency.
        """
        if self.storage is None:
            return
        try:
            for key, pdf in uploads:
                await self.storage.put(key, pdf, "application/pdf")
        except StorageError as exc:
            # The backend is unreachable for a short time, so raise a 503. The message
            # must not leak a path.
            raise ServiceUnavailableError(
                "Protocol rendering temporarily unavailable."
            ) from exc

    async def _send(self, protocol: Protocol, pdf: bytes | None) -> None:
        """Mail the protocol to MAIL_LIST(gremium) under an idempotency key.

        The mail carries the PDF as an attachment. The subject and the body name the
        Gremium and the meeting. The HTML version uses the branded mail layout. The
        mail holds no link, by design. The former `/api/protocols/{id}/pdf` link
        needed a login and `meeting.manage`. It was broken for the members and for the
        external list addresses.
        """
        if self.mail_queue is None:
            return
        recipients = await self._recipients(protocol.gremium_id)
        recipients = await filter_recipients_by_preference(
            self.session, recipients, "protocol"
        )
        if not recipients:
            return
        gremium_name = await self.session.scalar(
            select(Gremium.name).where(Gremium.id == protocol.gremium_id)
        )
        meeting = await self.session.get(Meeting, protocol.meeting_id)
        subject = "Sitzungsprotokoll"
        if gremium_name:
            subject += f" {gremium_name}"
        if meeting is not None and meeting.date is not None:
            subject += f" — {meeting.date.strftime('%d.%m.%Y')}"
        lines = []
        if meeting is not None:
            lines.append(f"Sitzung: {meeting.title}")
        if gremium_name:
            lines.append(f"Gremium: {gremium_name}")
        if meeting is not None and meeting.date is not None:
            lines.append(f"Datum: {meeting.date.strftime('%d.%m.%Y')}")
        intro = "Das Sitzungsprotokoll wurde finalisiert."
        if pdf is not None:
            intro = (
                "Das Sitzungsprotokoll wurde finalisiert und liegt als PDF bei."
            )
        text = intro + ("\n\n" + "\n".join(lines) if lines else "") + "\n"
        attachments: tuple[MailAttachment, ...] = ()
        if pdf is not None:
            attachments = (
                MailAttachment(
                    filename="protokoll.pdf", mime="application/pdf", content=pdf
                ),
            )
        settings = self.settings or get_settings()
        html = render_layout(
            content_html=text_to_html(text),
            title=subject,
            site_name=settings.mail_from_name,
            base_url=settings.public_base_url,
            reason=reason_text("protocol", "de"),
            lang="de",
        )
        await self.mail_queue.enqueue(
            MailMessage(
                to=tuple(recipients),
                subject=subject,
                text=text,
                html=html,
                idempotency_key=compute_idempotency_key(
                    "protocol_finalized", str(protocol.id)
                ),
                attachments=attachments,
            )
        )

    async def _recipients(self, gremium_id: UUID) -> list[str]:
        """Build the flat and deduplicated recipient list of the Gremium.

        The list is the union of the active Gremium members and the configured extra
        lists (`mail_list`). A member counts as active inside the term window and with
        a non-NULL email. The extra addresses get the protocol in addition to the
        members, not instead of them.
        """
        seen: dict[str, None] = {}
        members = await RecipientResolver(self.session).resolve(
            [{"kind": "gremium", "ref": str(gremium_id)}]
        )
        for addr in members:
            seen.setdefault(addr, None)
        lists = (
            await self.session.execute(
                select(MailList.recipients).where(
                    MailList.gremium_id == gremium_id, MailList.active.is_(True)
                )
            )
        ).scalars().all()
        for recipients in lists:
            for addr in recipients or []:
                seen.setdefault(addr, None)
        return list(seen)

    @staticmethod
    def _ensure_draft(protocol: Protocol) -> None:
        if protocol.status == "final":
            raise ConflictError(
                "Protocol is finalized and read-only.", code="conflict"
            )
        if protocol.status == "rendering":
            # The content is frozen during the background render. The PDF would
            # otherwise show a different state than the editor.
            raise ConflictError(
                "Protocol is being rendered and is read-only.", code="conflict"
            )

    async def _get_vote(self, vote_id: UUID) -> Vote:
        vote = await self.session.get(Vote, vote_id)
        if vote is None:
            raise NotFoundError(f"vote {vote_id} not found")
        return vote


def _vote_title(application_id: UUID | None, question: str | None = None) -> str:
    """Build the snippet heading of an embedded vote.

    For an application item, the heading is a short reference to the application. For
    a generic decision question without an application, the heading is the question
    itself. The protokollant can edit the heading in the editor.
    """
    if application_id is not None:
        return f"Abstimmung – Antrag {str(application_id)[:8]}"
    return question.strip() if question and question.strip() else "Beschlussfrage"
