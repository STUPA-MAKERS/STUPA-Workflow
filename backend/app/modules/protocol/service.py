"""Protocol service.

The service binds to an `AsyncSession` and drives the protocol lifecycle.

* `get_or_create` creates or loads the protocol of a meeting. It is idempotent
  through the UNIQUE `meeting_id`. It takes `gremium_id` and `cd_variant` from
  the meeting and the Gremium.
* `update_markdown` updates the editor body. It accepts a draft only.
* `embed_votes` appends votes as Markdown snippets and writes
  `protocol_vote_ref`. It is idempotent and skips an already referenced vote. A
  vote of another meeting gives 422 `vote_not_in_meeting`.
* `start_finalize` starts the finalization once, and only after the close of the
  meeting. It writes `protocol_finalize`.
* `finalize` renders the Markdown through typst into a PDF. It stores the PDF
  in MinIO and mails it to MAIL_LIST(gremium). It sets `status='final'` and
  `sent_at`.

The service reuses the typst client, the object storage and the mail queue of
`app.modules.pdf` and `app.modules.notifications` without a change.

Failure discipline: if storage is off by design (dev or demo without MinIO),
`finalize` still completes. The protocol becomes `final` and the mail goes out
without a PDF link. If an EXISTING render or storage backend fails for a short
time, the service raises `ServiceUnavailableError` (503). The session dependency
then rolls back, the protocol stays draft and the caller can repeat the call.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date as _date
from datetime import datetime
from datetime import time as _time
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.applications.models import Application
from app.modules.applications.service import ApplicationsService
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.documents.service import ANLAGE_MARK, ApplicationPdfService, anlage_reference
from app.modules.files.cd_resolver import (
    cd_render_config,
    cd_variant_key_for_gremium,
    resolve_cd_variant_by_key,
)
from app.modules.files.storage import ObjectStorage, StorageError
from app.modules.gremien.models import Gremium
from app.modules.livevote.service import MeetingService
from app.modules.media.service import MediaService
from app.modules.meetings.agenda_service import agenda_order, title_of
from app.modules.meetings.keepers import agenda_positions, keeper_periods, principal_names
from app.modules.meetings.models import Meeting, MeetingAgendaItem, MeetingAttendance
from app.modules.meetings.protocol_models import Protocol, ProtocolVoteRef
from app.modules.meetings.roster import meeting_roster_filter, roster_filter
from app.modules.notifications.layout import (
    append_link_text,
    reason_text,
    render_layout,
    text_to_html,
)
from app.modules.notifications.links import protocol_link, public_protocol_url
from app.modules.notifications.mail import (
    MailAttachment,
    MailMessage,
    compute_idempotency_key,
)
from app.modules.notifications.queue import MailQueue
from app.modules.notifications.recipients import RecipientResolver
from app.modules.notifications.service import filter_recipients_by_preference
from app.modules.pdf.typst_client import TypstClient, TypstError
from app.modules.protocol.filename import protocol_pdf_filename
from app.modules.protocol.markdown import (
    ElectionLine,
    ElectionSnippet,
    KeeperLine,
    PollLine,
    PollSnippet,
    ProtocolDoc,
    build_election_snippet,
    build_poll_snippet,
    build_protocol_document,
    build_vote_snippet,
    demote_headings,
    guest_vote_note,
    mark_vote_blocks,
    protocol_variant_for,
    replace_vote_blocks,
    top_time_note,
    votes_in_body,
)
from app.modules.protocol.public import (
    PublicAttendance,
    PublicDecision,
    PublicSnapshot,
    PublicTop,
    apply_public_snapshot,
    meeting_day,
    passed_conditions,
)
from app.modules.protocol.schemas import ProtocolOut
from app.modules.voting.models import Vote
from app.modules.voting.schemas import ElectionResultOut, PollResultOut, VoteOut
from app.modules.voting.service import VotingService
from app.settings import Settings, get_settings
from app.shared.blackout import black_out, has_open_marker
from app.shared.config_schemas import ElectionConfig, PollConfig, PollOption
from app.shared.errors import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
    ValidationProblem,
)

logger = logging.getLogger("app.protocol")

#: Permanent failures of the public build after which the hourly heal job skips a
#: protocol. A switch of the gremium flag tries it again.
PUBLIC_RENDER_MAX_FAILURES = 3


def protocol_storage_key(protocol_id: UUID) -> str:
    """Build the deterministic MinIO key under the own `pdf/protocol/` prefix."""
    return f"pdf/protocol/{protocol_id}.pdf"


def protocol_public_storage_key(protocol_id: UUID) -> str:
    """Build the MinIO key of the redacted public protocol variant."""
    return f"pdf/protocol/{protocol_id}-public.pdf"


#: Placeholder for the body of a non-public agenda item in the public PDF. The
#: numbering stays and the content is redacted.
_NON_PUBLIC_PLACEHOLDER = "*(nicht-öffentlicher Tagesordnungspunkt)*"
#: Neutral heading for a non-public item in the public PDF. The original title can
#: encode the sensitive subject and must not reach the mailed variant.
_NON_PUBLIC_HEADING = "Nicht-öffentlicher Tagesordnungspunkt"


@dataclass(frozen=True, slots=True)
class BackfillResult:
    """The counts of one public backfill run."""

    done: int = 0
    transient: int = 0
    failed: int = 0


#: The outcome of the public backfill of one protocol.
BackfillOutcome = Literal["done", "transient", "failed"]


@dataclass(frozen=True, slots=True)
class HeaderMeta:
    """The person-related header data of one protocol variant.

    `present_count` holds the true number of attendees and feeds the quorum, also
    in the public variant that leaves the names out.
    """

    protokollant: str | None = None
    keepers: Sequence[KeeperLine] = field(default_factory=list)
    present: Sequence[str] = field(default_factory=list)
    excused: Sequence[str] = field(default_factory=list)
    absent: Sequence[str] = field(default_factory=list)
    present_count: int = 0
    excused_count: int = 0
    absent_count: int = 0
    guest_count: int = 0
    datalines: Sequence[str] = field(default_factory=list)


class ProtocolService:
    """Run the protocol operations and the finalization over the shared render stack."""

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
            base.with_for_update().execution_options(populate_existing=True)
            if for_update
            else base
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

    async def authorize_write_meeting(
        self, meeting_id: UUID, principal: Principal
    ) -> None:
        """Check the write access to the protocol of a meeting (create or load).

        One of these rights is enough: the admin role, the Gremium permission
        `session.manage`, the assigned protokollant role, or a Gremium role with
        `protocol.write`. The rule is the same as `can_write`.

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

        The caller needs the write access AND the Gremium permission
        `protocol.finalize` in the Gremium of the meeting (or the admin role). This
        rule is stricter than the rule for a draft write. `MeetingService.can_finalize`
        holds the rule, so the `canFinalize` flag of the meeting agrees with it.

        Raises:
            ForbiddenError: The caller has no write access or lacks
                `protocol.finalize`.
        """
        protocol = await self._get(protocol_id)
        meeting = await self._meeting(protocol.meeting_id)
        svc = self._meeting_service()
        if not await svc.can_write(meeting, principal):
            raise ForbiddenError("not allowed to write this meeting's minutes")
        if not await svc.can_finalize(meeting, principal):
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
        stored = protocol.pdf_storage_key is not None and self.storage is not None
        return f"/api/protocols/{protocol.id}/pdf" if stored else None

    def _public_pdf_path(self, protocol: Protocol) -> str | None:
        """Build the app-relative path of the redacted public variant."""
        stored = protocol.public_pdf_storage_key is not None and self.storage is not None
        return f"/api/protocols/{protocol.id}/pdf/public" if stored else None

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

    async def pdf_filename(self, protocol_id: UUID, *, public: bool = False) -> str:
        """Return the download name of the protocol PDF: meeting title and day.

        Args:
            protocol_id: The protocol.
            public: `True` for the redacted variant (`_oeffentlich`).

        Raises:
            NotFoundError: The protocol or its meeting is missing (404).
        """
        protocol = await self._get(protocol_id)
        meeting = await self.session.get(Meeting, protocol.meeting_id)
        if meeting is None:
            raise NotFoundError(f"protocol {protocol_id} has no meeting")
        return protocol_pdf_filename(meeting.title, meeting_day(meeting), public=public)

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
        return await self._to_out(protocol)

    async def get_or_create(
        self, meeting_id: UUID, *, author: str | None = None
    ) -> ProtocolOut:
        """Create or load the protocol of a meeting (idempotent).

        The method is race-safe. On a parallel POST, `INSERT … ON CONFLICT
        (meeting_id) DO NOTHING` avoids the UNIQUE violation, so there is no
        `IntegrityError` and no 500. The re-select after the insert returns the same
        row in BOTH cases: created here, or won by the parallel request.

        The protocol appears only when the meeting starts (planned to live), because a
        user must never create the minutes by hand in advance. The re-select finds no
        row only when the row disappeared between the insert and the select.

        Raises:
            NotFoundError: The meeting does not exist (404).
            ConflictError: The meeting has not started yet.
        """
        existing = await self._by_meeting(meeting_id)
        if existing is not None:
            return await self._to_out(existing)

        meeting = await self.session.get(Meeting, meeting_id)
        if meeting is None:
            raise NotFoundError(f"meeting {meeting_id} not found")
        if meeting.status == "planned":
            raise ConflictError(
                "the meeting has not started — its minutes are created on start",
                code="meeting_not_started",
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
        if protocol is None:
            raise NotFoundError(f"protocol for meeting {meeting_id} not found")
        return await self._to_out(protocol)

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
        return await self._to_out(protocol)

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
        self, protocol_id: UUID, vote_ids: Sequence[UUID]
    ) -> ProtocolOut:
        """Append votes as snippets and write `protocol_vote_ref` (idempotent).

        A vote that is already embedded gets no second snippet. An unknown vote gives
        404, which avoids an FK `IntegrityError`. A vote of another meeting gives 422,
        which keeps a vote of another meeting, maybe of another gremium, out of these
        minutes. The insert uses `ON CONFLICT (protocol_id, vote_id) DO NOTHING`, so a
        parallel request that wrote the ref first causes no duplicate snippet, no
        `IntegrityError` and no 500.
        """
        protocol = await self._get(protocol_id)
        self._ensure_draft(protocol)
        already = frozenset(
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
        fresh = tuple(dict.fromkeys(v for v in vote_ids if v not in already))
        embedded = [
            await self._embed_one(protocol_id, protocol.meeting_id, vote_id, voting)
            for vote_id in fresh
        ]
        snippets = [snippet for snippet in embedded if snippet is not None]

        if snippets:
            body = protocol.markdown.rstrip("\n")
            joined = "\n\n".join(snippets)
            protocol.markdown = f"{body}\n\n{joined}\n" if body else f"{joined}\n"
            await self.session.flush()
        await self.session.commit()
        return await self._to_out(protocol)

    async def _embed_one(
        self, protocol_id: UUID, meeting_id: UUID, vote_id: UUID, voting: VotingService
    ) -> str | None:
        """Check one vote, write its `protocol_vote_ref` and return its snippet.

        Returns:
            The snippet, or `None` when a parallel request wrote the ref first.
        """
        await self._get_vote(vote_id, meeting_id=meeting_id)
        inserted = (
            await self.session.execute(
                pg_insert(ProtocolVoteRef)
                .values(protocol_id=protocol_id, vote_id=vote_id)
                .on_conflict_do_nothing(constraint="uq_protocol_vote_ref")
                .returning(ProtocolVoteRef.id)
            )
        ).first()
        if inserted is None:
            return None
        view = await voting.get(vote_id)
        return _snippet(view, _vote_title(view.application_id, view.question), tz=self._tz())

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

    async def set_public_withheld(
        self, protocol_id: UUID, withheld: bool, *, actor: str
    ) -> ProtocolOut:
        """Hold back a protocol from the public protocols page, or release it.

        The change works in every status, also on a final protocol. A change
        writes `protocol_publication` with the old and the new value. The same
        value again is a no-op without an audit entry.
        """
        protocol = await self._get(protocol_id, for_update=True)
        old = bool(protocol.public_withheld)
        if old != withheld:
            protocol.public_withheld = withheld
            await self._audit_publication(protocol, actor, old, withheld)
            await self.session.flush()
        await self.session.commit()
        return await self._to_out(protocol)

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

        The typst render runs BEFORE the commit. A permanent render error (4xx) or a
        short typst outage (5xx) rolls the session back, and the protocol stays draft.
        The storage `put` and the mail enqueue run only AFTER a successful commit,
        because a failed commit would otherwise leave an orphaned MinIO object and an
        enqueued send job for a row that never became `final`.

        The method renders two PDFs when the meeting has a non-public item or the
        gremium publishes its protocols: the full internal PDF and the redacted public
        PDF. With a non-public item or a blackout mark (000691) only the public variant
        is mailed, so neither a non-public item nor a marked name reaches the list. A
        gremium that publishes its protocols always gets the public variant, for the
        public page.
        """
        protocol = await self._get(protocol_id)
        if protocol.status == "final":
            return await self._to_out(protocol)

        mail_public = await self._mails_public(protocol)
        gremium = await self.session.get(Gremium, protocol.gremium_id)
        uploads, mail_pdf = (
            await self._render_both(protocol, mail_public=mail_public)
            if mail_public or bool(getattr(gremium, "protocols_public", False))
            else await self._render_internal(protocol)
        )
        protocol.status = "final"
        protocol.sent_at = now
        await self.session.flush()
        await self.session.commit()
        await self._store(uploads)
        await self._send(protocol, mail_pdf)
        return await self._to_out(protocol)

    async def _render_both(
        self, protocol: Protocol, *, mail_public: bool
    ) -> tuple[tuple[tuple[str, bytes], ...], bytes | None]:
        """Render the internal and the public PDF and store the public snapshot.

        Returns:
            The uploads, and the PDF for the mail: the public one when a non-public
            item or a blackout mark exists, else the internal one.
        """
        internal_md = await self._build_document(protocol, public=False)
        internal_pdf = await self._render_pdf(protocol, internal_md, public=False)
        snapshot = PublicSnapshot()
        public_md = await self._build_document(protocol, public=True, snapshot=snapshot)
        public_pdf = await self._render_pdf(protocol, public_md, public=True)
        apply_public_snapshot(protocol, snapshot, public_pdf)
        uploads = (
            *_upload(protocol_storage_key(protocol.id), internal_pdf),
            *_upload(protocol_public_storage_key(protocol.id), public_pdf),
        )
        return uploads, (public_pdf if mail_public else internal_pdf)

    async def _render_internal(
        self, protocol: Protocol
    ) -> tuple[tuple[tuple[str, bytes], ...], bytes | None]:
        """Render the internal PDF only, which the mail then carries."""
        markdown = await self._build_document(protocol)
        pdf = await self._render_pdf(protocol, markdown)
        return _upload(protocol_storage_key(protocol.id), pdf), pdf

    def _missing_public_clause(self) -> ColumnElement[bool]:
        """Return the rule "final, and the public version is missing"."""
        missing = Protocol.public_content.is_(None)
        renders = self.storage is not None and self.typst is not None
        return and_(
            Protocol.status == "final",
            or_(missing, Protocol.public_pdf_storage_key.is_(None)) if renders else missing,
        )

    async def backfill_public(
        self, gremium_id: UUID, *, retry_failed: bool = True
    ) -> BackfillResult:
        """Build the missing public versions of the final protocols of a gremium.

        The job runs after a gremium switched `protocols_public` on. A final
        protocol without a public snapshot, or without a public PDF while storage is
        on, gets both, with the same renderer and variant as the finalization. Each
        protocol commits on its own. A failure of one protocol does not stop the
        others: the protocol stays hidden (fail closed) and the result counts it.

        A permanent failure (for example a render error in the text) counts up
        `public_render_failures`. With `retry_failed=False` (the hourly heal job),
        a protocol at `PUBLIC_RENDER_MAX_FAILURES` is skipped, so the same error does
        not run every hour. A switch of the gremium flag retries it.

        Any exception of one protocol is caught and logged, because one bad protocol
        must not stop the job.
        """
        base = select(Protocol.id).where(
            Protocol.gremium_id == gremium_id, self._missing_public_clause()
        )
        stmt = (
            base
            if retry_failed
            else base.where(Protocol.public_render_failures < PUBLIC_RENDER_MAX_FAILURES)
        )
        ids = (await self.session.scalars(stmt.order_by(Protocol.created_at))).all()
        outcomes = Counter([await self._backfill_outcome(protocol_id) for protocol_id in ids])
        return BackfillResult(
            done=outcomes["done"], transient=outcomes["transient"], failed=outcomes["failed"]
        )

    async def _backfill_outcome(self, protocol_id: UUID) -> BackfillOutcome:
        """Run the backfill of one protocol and classify its outcome.

        A failure rolls the session back, so the next protocol starts clean. Any
        exception is caught and logged, because one bad protocol must not stop the job.
        """
        try:
            await self._backfill_one(protocol_id)
        except ServiceUnavailableError:
            await self.session.rollback()
            return "transient"
        except Exception:
            logger.exception("public backfill failed (protocol=%s)", protocol_id)
            await self.session.rollback()
            await self._count_render_failure(protocol_id)
            return "failed"
        return "done"

    async def gremien_missing_public(self) -> list[UUID]:
        """List the public gremien with a final protocol that lacks its public version.

        A protocol counts when it is not held back and has no snapshot, or no public PDF
        while storage is on.

        The hourly heal job runs the backfill for them, so a protocol whose build
        failed or raced appears without a new switch of the gremium flag.
        """
        rows = await self.session.scalars(
            select(Protocol.gremium_id)
            .join(Gremium, Gremium.id == Protocol.gremium_id)
            .where(
                Gremium.protocols_public.is_(True),
                Protocol.public_withheld.is_(False),
                Protocol.public_render_failures < PUBLIC_RENDER_MAX_FAILURES,
                self._missing_public_clause(),
            )
            .distinct()
        )
        return list(rows.all())

    async def _count_render_failure(self, protocol_id: UUID) -> None:
        """Count a permanent failure of the public build, in its own commit.

        At `PUBLIC_RENDER_MAX_FAILURES` the method logs a warning once; the hourly
        heal job then skips the protocol.
        """
        protocol = await self.session.get(Protocol, protocol_id)
        if protocol is None:
            return
        protocol.public_render_failures = int(protocol.public_render_failures or 0) + 1
        if protocol.public_render_failures == PUBLIC_RENDER_MAX_FAILURES:
            logger.warning(
                "public version of protocol %s failed %s times; the heal job skips it "
                "until the gremium flag is switched again",
                protocol_id,
                PUBLIC_RENDER_MAX_FAILURES,
            )
        await self.session.commit()

    async def _backfill_one(self, protocol_id: UUID) -> None:
        """Build the public snapshot and the public PDF of one locked final protocol.

        A protocol that a parallel job built while this one waited for the lock is left
        as it is. A public PDF that exists without a size (an older protocol with a
        non-public TOP) is read from storage to get its size.
        """
        protocol = await self._get(protocol_id, for_update=True)
        pdf_done = protocol.public_pdf_storage_key is not None or self.storage is None
        if protocol.public_content is not None and pdf_done:
            await self.session.commit()
            return
        snapshot = PublicSnapshot()
        markdown = await self._build_document(protocol, public=True, snapshot=snapshot)
        key = protocol.public_pdf_storage_key
        pdf = (
            await self._render_pdf(protocol, markdown, public=True)
            if key is None
            else (await self._stored_pdf(key) if protocol.public_pdf_size is None else None)
        )
        uploads = _upload(protocol_public_storage_key(protocol.id), pdf) if key is None else ()
        apply_public_snapshot(protocol, snapshot, pdf)
        protocol.public_render_failures = 0
        await self.session.flush()
        await self.session.commit()
        await self._store(uploads)

    async def _stored_pdf(self, key: str) -> bytes | None:
        """Read a stored PDF to learn its size, or `None` without storage or on an error."""
        if self.storage is None:
            return None
        try:
            return await self.storage.get(key)
        except StorageError:
            return None

    async def _build_document(
        self,
        protocol: Protocol,
        *,
        public: bool = False,
        snapshot: PublicSnapshot | None = None,
    ) -> str:
        """Build the protocol Markdown document with its header.

        The per-item editor, that is the agenda, is the source of truth. If agenda items
        exist, the document is assembled from their Markdown bodies and the decision
        snippets. If not, it falls back to the free text in `protocol.markdown`, which
        is then the whole public body too.

        `public=True` redacts a non-public item and the header metadata. The mailed
        variant must not carry the names of the attendees, of the excused members, of
        the absentees or of the protocol keepers. `_header_meta` then returns empty name
        lists and the counters only. The quorum statement rests on the counters and
        stays meaningful.
        """
        meeting = await self.session.get(Meeting, protocol.meeting_id)
        gremium = await self.session.get(Gremium, protocol.gremium_id)
        title = meeting.title if meeting is not None else "Protokoll"
        assembled = await self._assemble_from_agenda(
            protocol.meeting_id,
            public=public,
            tops=snapshot.tops if snapshot is not None else None,
        )
        header = await self._header_meta(meeting, public=public)
        free_text = (
            black_out(protocol.markdown) if public and protocol.markdown else protocol.markdown
        )
        if snapshot is not None:
            snapshot.attendance = PublicAttendance(
                present=header.present_count,
                excused=header.excused_count,
                absent=header.absent_count,
                guests=header.guest_count,
            )
            if not assembled:
                snapshot.markdown = free_text
        date, start_time = self._start_of(meeting)
        return build_protocol_document(
            ProtocolDoc(
                title=title,
                gremium_name=getattr(gremium, "name", None) if gremium is not None else None,
                cd_variant=protocol.cd_variant,
                date=date,
                start_time=start_time,
                end_time=self._local_end_time(
                    getattr(meeting, "closed_at", None) if meeting is not None else None
                ),
                started_at=(
                    f"{date.isoformat()} {start_time.strftime('%H:%M')}"
                    if date is not None and start_time is not None
                    else None
                ),
                protokollant=header.protokollant,
                keepers=header.keepers,
                present=header.present,
                excused=header.excused,
                absent=header.absent,
                datalines=header.datalines,
                quorate=await self._quorate(gremium, meeting, header.present_count),
                markdown=assembled or free_text,
            )
        )

    def _tz(self) -> ZoneInfo:
        settings = self.settings or get_settings()
        return ZoneInfo(settings.local_timezone)

    def _start_of(self, meeting: Meeting | None) -> tuple[_date | None, _time | None]:
        """Return the local date and time of the start: the real one, else the planned.

        `started_at = COALESCE(meeting.started_at, planned start)`. A meeting
        from before the real start existed shows the planned date and time.
        """
        if meeting is None:
            return None, None
        started = getattr(meeting, "started_at", None)
        if isinstance(started, datetime):
            local = started.astimezone(self._tz())
            return local.date(), local.time().replace(second=0, microsecond=0)
        return meeting.date, getattr(meeting, "start_time", None)

    def _local_end_time(self, closed_at: object) -> _time | None:
        """Convert `meeting.closed_at` from UTC to local time for the end line."""
        return (
            closed_at.astimezone(self._tz()).time().replace(second=0, microsecond=0)
            if isinstance(closed_at, datetime)
            else None
        )

    def _local_hhmm(self, value: datetime | None) -> str | None:
        return None if value is None else value.astimezone(self._tz()).strftime("%H:%M")

    async def _keeper_lines(self, meeting: Meeting) -> list[KeeperLine]:
        """Build the header lines of the keeper periods that started.

        A TOP number comes from the current agenda order. A period without an agenda
        item, or with a deleted one, carries the time only.
        """
        periods = [p for p in await keeper_periods(self.session, [meeting.id]) if p.from_at]
        if not periods:
            return []
        names = await principal_names(self.session, {p.principal_id for p in periods})
        positions = await agenda_positions(self.session, [meeting.id])
        return [
            KeeperLine(
                name=names.get(p.principal_id) or "—",
                from_time=self._local_hhmm(p.from_at),
                to_time=self._local_hhmm(p.to_at),
                from_top=positions.get(p.from_agenda_item_id) if p.from_agenda_item_id else None,
                to_top=positions.get(p.to_agenda_item_id) if p.to_agenda_item_id else None,
            )
            for p in periods
        ]

    async def _quorate(
        self, gremium: object | None, meeting: Meeting | None, present_count: int
    ) -> bool | None:
        """Compute the quorum from the attendees and the members of the meeting.

        The members are the roster of the meeting: the members of the Gremium,
        plus each principal with an attendance record (see
        `app.modules.meetings.roster`). Without a meeting the members of the
        Gremium count. The threshold is `gremium.quorum_percent` when
        that value is set. If not, the threshold is more than half of the members.

        Returns:
            The quorum result, or `None` when the Gremium or its members are missing.
            The PDF then shows no quorum statement.
        """
        gremium_id = getattr(gremium, "id", None)
        if gremium_id is None:
            return None
        where = (
            meeting_roster_filter(meeting)
            if meeting is not None and getattr(meeting, "gremium_id", None) == gremium_id
            else roster_filter(gremium_id)
        )
        members = (
            await self.session.scalar(
                select(func.count()).select_from(PrincipalRow).where(where)
            )
        ) or 0
        percent = getattr(gremium, "quorum_percent", None)
        quorate = (
            present_count * 100 >= percent * members
            if percent is not None
            else present_count * 2 > members
        )
        return None if members == 0 else quorate

    async def _header_meta(self, meeting: Meeting | None, *, public: bool = False) -> HeaderMeta:
        """Resolve the protocol keepers and the attendance groups for the header.

        A list entry holds the display name of the principal, or the sub as a
        fallback. The excused members are their own group. `public=True`
        redacts the person-related header metadata for the mailed variant. The full
        attendance lists and the names of the protocol keepers must never go
        external. The method then emits the counters only, as the data lines
        `Anwesend: n`, `Entschuldigt: n` and `Abwesend: n`.

        The guests of a public meeting appear as a count only, never by name. The legacy
        key `protokollant` names every keeper once, for a render service that does not
        read `keepers`.
        """
        if meeting is None:
            return HeaderMeta()
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
        excused = [name or sub for status, name, sub in rows if status == "excused"]
        absent = [name or sub for status, name, sub in rows if status == "absent"]
        present_count = len(present)
        from app.modules.livevote.guests import GuestService

        guests = await GuestService(self.session).attended_count(meeting.id)
        guest_lines = [f"Gäste: {guests}"] if guests else []
        if public:
            return HeaderMeta(
                present_count=present_count,
                excused_count=len(excused),
                absent_count=len(absent),
                guest_count=guests,
                datalines=[
                    f"Anwesend: {present_count}",
                    f"Entschuldigt: {len(excused)}",
                    f"Abwesend: {len(absent)}",
                    *guest_lines,
                ],
            )
        keepers = await self._keeper_lines(meeting)
        protokollant = (
            ", ".join(dict.fromkeys(k.name for k in keepers))
            if keepers
            else await self._legacy_protokollant(meeting)
        )
        return HeaderMeta(
            protokollant=protokollant,
            keepers=keepers,
            present=present,
            excused=excused,
            absent=absent,
            present_count=present_count,
            datalines=guest_lines,
        )

    async def _legacy_protokollant(self, meeting: Meeting) -> str | None:
        """Return the name of `meeting.protokollant_id` for a meeting without periods."""
        if getattr(meeting, "protokollant_id", None) is None:
            return None
        return await self.session.scalar(
            select(PrincipalRow.display_name).where(PrincipalRow.id == meeting.protokollant_id)
        )

    async def _texts(self, protocol: Protocol) -> list[tuple[int | None, str]]:
        """Return the Markdown texts: the TOP bodies with their numbers, then the free text."""
        bodies = (
            await self.session.execute(
                select(MeetingAgendaItem.body)
                .where(MeetingAgendaItem.meeting_id == protocol.meeting_id)
                .order_by(*agenda_order())
            )
        ).scalars().all()
        tops = [(number, body) for number, body in enumerate(bodies, start=1) if body]
        return [*tops, *([(None, protocol.markdown)] if protocol.markdown else [])]

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
        self,
        meeting_id: UUID,
        *,
        public: bool = False,
        tops: list[PublicTop] | None = None,
    ) -> str:
        """Build the protocol Markdown from the agenda item bodies and their votes.

        `public=True` redacts a non-public item. The heading stays, and so does the
        numbering. A placeholder replaces the body and the decision snippets.
        With `tops`, the method also collects the structured public TOPs for the
        public protocols page, in the same pass and without extra queries.

        The items follow the agenda order of the meeting page, so "TOP n" in the PDF and
        the TOP numbers of the keeper periods agree. An application item has no title of
        its own: it shows the title of its application, as on the meeting page.

        Each item heading is a top-level `#` WITHOUT a "TOP n:" prefix, because the
        typst service numbers the sections itself as "TOP 1", "TOP 2" and so on. A `##`
        would get the number "TOP 0.1", and a manual prefix would appear twice. The body
        headings move down one level, because otherwise every `#` counts as its own
        agenda item. A public non-public item gets a neutral heading, because the
        original title can encode the sensitive subject.

        A cancelled vote has no result and gets no empty tally box. In the public text
        an election callout of the protokollant shows the elected names only, not every
        candidate with the votes. A vote that the protokollant already put into the text
        with the same snippet gets no second box, also for two votes with one question.
        A poll is no decision and stays out of the public decisions. The public list
        shows a closed decision also when its snippet is already in the text, and
        `inText` tells the detail page to show no second box for it.
        """
        items = (
            await self.session.execute(
                select(MeetingAgendaItem)
                .where(MeetingAgendaItem.meeting_id == meeting_id)
                .order_by(*agenda_order())
            )
        ).scalars().all()
        if not items:
            return ""
        app_ids = [
            app_id
            for item in items
            if (app_id := getattr(item, "application_id", None)) is not None
        ]
        app_rows = (
            (
                await self.session.execute(
                    select(Application.id, Application.data).where(Application.id.in_(app_ids))
                )
            ).all()
            if app_ids
            else []
        )
        app_titles = {app_id: title_of(data) for app_id, data in app_rows}
        voting = VotingService(self.session)
        assembled = [
            await self._assemble_item(number, item, app_titles, voting, public=public)
            for number, item in enumerate(items, start=1)
        ]
        if tops is not None:
            tops.extend(top for _, top in assembled)
        return "\n\n".join(block for block, _ in assembled) + "\n"

    async def _assemble_item(
        self,
        number: int,
        item: MeetingAgendaItem,
        app_titles: Mapping[UUID, str | None],
        voting: VotingService,
        *,
        public: bool,
    ) -> tuple[str, PublicTop]:
        """Build the Markdown block and the public TOP of one agenda item.

        A non-public item of the public variant gets the neutral heading and the
        placeholder, and its TOP keeps the number only. An item that the meeting
        reached gets an empty time note in front of its heading, also when it is
        non-public, because the time tells nothing about the subject.
        """
        app_id = getattr(item, "application_id", None)
        own = item.title or (app_titles.get(app_id) if app_id is not None else None)
        heading = (own or "Tagesordnungspunkt").strip()
        block, top = (
            _redacted_item(number)
            if public and item.non_public
            else await self._item_with_votes(number, item, heading, voting, public=public)
        )
        note = top_time_note(getattr(item, "started_at", None), self._tz())
        return (f"{note}\n\n{block}" if note else block), top

    async def _item_with_votes(
        self,
        number: int,
        item: MeetingAgendaItem,
        heading: str,
        voting: VotingService,
        *,
        public: bool,
    ) -> tuple[str, PublicTop]:
        """Build the block of an agenda item from its body and its non-cancelled votes.

        A vote whose snippet is already in the body gets no second box, and a repeated
        vote gets its mark line, in the body or below its own box.
        """
        stripped = item.body.strip() if item.body and item.body.strip() else ""
        raw = black_out(stripped) if public else stripped
        votes = (
            await self.session.execute(
                select(Vote)
                .where(
                    Vote.agenda_item_id == item.id,
                    Vote.status != "cancelled",
                )
                .order_by(Vote.created_at)
            )
        ).scalars().all()
        views = [await voting.get(vote.id) for vote in votes]
        marks = _repeat_marks(votes, views)
        tz = self._tz()
        body = replace_vote_blocks(raw, _election_pairs(views, tz)) if public else raw
        plain = [_snippet(view, "Beschlussfrage", public=public, tz=tz) for view in views]
        found = votes_in_body(body, plain)
        marked = mark_vote_blocks(
            body,
            [
                (snippet, marks[vote.id])
                for vote, snippet, in_text in zip(votes, plain, found, strict=True)
                if in_text and vote.id in marks
            ],
        )
        snippets = [
            f"{snippet}\n> {marks[vote.id]}" if vote.id in marks else snippet
            for vote, snippet in zip(votes, plain, strict=True)
        ]
        decisions = [
            PublicDecision.from_vote(view).model_copy(update={"in_text": in_text})
            for view, in_text in zip(views, found, strict=True)
            if getattr(view, "status", None) == "closed" and getattr(view, "kind", None) != "poll"
        ]
        anlage = (
            [anlage_reference(item.id, heading, public=public)]
            if getattr(item, "application_id", None) is not None
            else []
        )
        block = [
            f"# {heading}",
            *anlage,
            *([demote_headings(marked)] if marked else []),
            *(snippet for snippet, in_text in zip(snippets, found, strict=True) if not in_text),
        ]
        top = PublicTop(number=number, title=heading, markdown=marked or None, decisions=decisions)
        return "\n\n".join(block), top

    async def _anlage_assets(self, protocol: Protocol, *, public: bool) -> dict[str, bytes]:
        """Render the Antrag Anlagen of the TOPs of the meeting (spec 000884).

        Each TOP of an Antrag appends the Antrag PDF in the version that the Sitzung
        treated. The public variant blacks out the personal data and leaves out the
        Anlage of a non-public TOP.
        """
        items = list(
            (
                await self.session.scalars(
                    select(MeetingAgendaItem).where(
                        MeetingAgendaItem.meeting_id == protocol.meeting_id,
                        MeetingAgendaItem.application_id.is_not(None),
                    )
                )
            ).all()
        )
        if not items:
            return {}
        pdfs = ApplicationPdfService(
            self.session,
            storage=self.storage,
            typst=self.typst,
            settings=self.settings or get_settings(),
        )
        return await pdfs.anlage_assets(ApplicationsService(self.session), items, public=public)

    async def _render_pdf(
        self, protocol: Protocol, markdown: str, *, public: bool = False
    ) -> bytes | None:
        """Render the Markdown with typst and return the PDF bytes.

        The render runs BEFORE the commit. The method sets the key column but does
        NOT upload. The storage `put` runs after the commit in `_store`.
        `public=True` sets `public_pdf_storage_key` instead of `pdf_storage_key`.

        Storage is the on/off switch: without it, finalize continues without a PDF (demo
        or contract CI without MinIO). The protocol uses the CD key that it snapshots
        from its gremium at creation, so it keeps its design after the gremium moves to
        another one. A protocol always renders with a protocol variant: the design
        contributes logos, but it does not pick the document shape, because a report
        shape loses the TOP numbering, the vote boxes and the signature page. The
        uploaded images of the text go next to the logos. An image that is missing or
        exceeds the budget stays out, and the PDF shows its alt text. The body is
        user-written. The render service converts it into data before Typst sees it, so
        no part of it runs as code there.

        A typst 4xx is a permanent input error, for example a malformed formula. It is
        not retried and gives the scrubbed reason instead of a misleading 503. A 5xx or
        a transport error stays transient.

        Returns:
            The PDF bytes, or `None` when storage is off (dev). The method then
            renders nothing.

        Raises:
            BadRequestError: typst reported a permanent error (400).
            ServiceUnavailableError: typst failed for a short time (503). The draft
                survives.
        """
        if self.storage is None or self.typst is None:
            return None
        try:
            cd = await resolve_cd_variant_by_key(
                self.session, self.storage, protocol.cd_variant
            )
            variant = protocol_variant_for(protocol.cd_variant)
            config = cd_render_config(cd) if cd else None
            media = MediaService(self.session, storage=self.storage)
            images = await media.render_assets(markdown)
            documents = await media.render_documents(markdown)
            anlagen = (
                await self._anlage_assets(protocol, public=public)
                if ANLAGE_MARK in markdown
                else {}
            )
            assets = {**(cd.assets if cd else {}), **images, **documents, **anlagen} or None
            pdf = await self.typst.render_pdf(
                markdown, variant=variant, config=config, assets=assets
            )
        except TypstError as exc:
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

    async def _store(self, uploads: Sequence[tuple[str, bytes]]) -> None:
        """Upload the rendered PDFs to object storage AFTER a successful commit.

        The MinIO object appears only now, so a failed commit leaves no orphaned
        object. With storage off, `uploads` is empty because `_render_pdf` returned
        `None`.

        The 503 message does not name the storage path.

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
            raise ServiceUnavailableError(
                "Protocol rendering temporarily unavailable."
            ) from exc

    async def _send(self, protocol: Protocol, pdf: bytes | None) -> None:
        """Mail the protocol to MAIL_LIST(gremium) under an idempotency key.

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
        members = await self._recipients(protocol.gremium_id)
        recipients = await filter_recipients_by_preference(self.session, members, "protocol")
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
        subject = "Sitzungsprotokoll" + (f" {gremium_name}" if gremium_name else "") + (
            f" — {day}" if day else ""
        )
        settings = self.settings or get_settings()
        link = protocol_link(settings, protocol.meeting_id)
        public = (
            gremium is not None
            and bool(getattr(gremium, "protocols_public", False))
            and protocol.status == "final"
            and not protocol.public_withheld
            and protocol.public_content is not None
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
        text = append_link_text(body, link.url, link.label("de"))
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
        html = render_layout(
            content_html=text_to_html(body),
            title=subject,
            site_name=settings.mail_from_name,
            base_url=settings.public_base_url,
            reason=reason_text("protocol", "de"),
            lang="de",
            action_url=link.url,
            action_label=link.label("de"),
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
            raise ConflictError(
                "Protocol is finalized and read-only.", code="protocol_finalized"
            )
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


def _snippet(
    view: VoteOut, fallback: str, *, public: bool = False, tz: ZoneInfo | None = None
) -> str:
    """Build the protocol callout of a vote: a motion, an election or a poll.

    ``tz`` is the local time zone of the dates of a date poll.
    """
    match getattr(view, "kind", "motion"):
        case "election" if view.election is not None:
            return build_election_snippet(_election_snippet(view), public=public)
        case "poll" if view.poll is not None:
            return build_poll_snippet(
                poll_snippet_of(
                    view.poll,
                    view.poll_result if view.status == "closed" else None,
                    question=_with_attempt(view.question or "Umfrage", view),
                    tz=tz or ZoneInfo("Europe/Berlin"),
                )
            )
        case _:
            return build_vote_snippet(
                view.question or fallback,
                view.tally.counts,
                question=_with_attempt(view.question or fallback, view),
                note=_guest_note(view),
                conditions=passed_conditions(view),
            )


def _election_pairs(views: Sequence[VoteOut], tz: ZoneInfo) -> list[tuple[str, str]]:
    """Pair the internal and the public callout of each election, for the public text."""
    return [
        (
            _snippet(view, "Beschlussfrage", tz=tz),
            _snippet(view, "Beschlussfrage", public=True, tz=tz),
        )
        for view in views
        if getattr(view, "kind", "motion") == "election"
    ]


def _redacted_item(number: int) -> tuple[str, PublicTop]:
    """Return the block and the TOP of a non-public item in the public variant."""
    block = "\n\n".join([f"# {_NON_PUBLIC_HEADING}", _NON_PUBLIC_PLACEHOLDER])
    return block, PublicTop(number=number, title=None, nonPublic=True)


def _upload(key: str, pdf: bytes | None) -> tuple[tuple[str, bytes], ...]:
    """Return the upload of a rendered PDF, or none when storage is off."""
    return ((key, pdf),) if pdf is not None else ()


def _repeat_marks(votes: Sequence[Vote], views: Sequence[VoteOut]) -> dict[UUID, str]:
    """Return the mark line of each repeated vote of an agenda item, by vote id.

    A vote counts as repeated once its repeat opened: a prepared repeat can still go
    away, and then the first result stands alone.
    """
    return {
        source: repeat_mark(view)
        for vote, view in zip(votes, views, strict=True)
        if (source := getattr(vote, "repeat_of_id", None)) is not None
        and getattr(vote, "status", None) in ("open", "closed")
    }


def _with_attempt(question: str, view: VoteOut) -> str:
    """Add the number of a repeat to the head of a motion or a poll.

    The repeat has the question of the vote it repeats, so its head names the attempt
    („Frage (2. Abstimmung)“). Each attempt then has its own head line, which
    `votes_in_body` and the editor match on.
    """
    attempt = getattr(view, "attempt", 1) or 1
    return f"{question.strip()} ({attempt}. Abstimmung)" if attempt > 1 else question


def repeat_mark(repeat: VoteOut) -> str:
    """Return the line that marks a repeated vote in the protocol."""
    attempt = getattr(repeat, "attempt", 2) or 2
    number = (getattr(repeat, "round", 1) or 1) + attempt - 1
    return (
        f"Wiederholt, siehe {number}. Wahlgang."
        if getattr(repeat, "kind", "motion") == "election"
        else f"Wiederholt, siehe {attempt}. Abstimmung."
    )


def _election_snippet(view: VoteOut) -> ElectionSnippet:
    """Map an election and its stored result on the protocol view.

    The caller checks that the vote is an election.
    """
    assert view.election is not None
    return election_snippet_of(
        view.election,
        view.election_result,
        question=view.question,
        round_=view.round,
        attempt=getattr(view, "attempt", 1) or 1,
    )


def election_snippet_of(
    election: ElectionConfig,
    result: ElectionResultOut | None,
    *,
    question: str | None,
    round_: int,
    attempt: int = 1,
) -> ElectionSnippet:
    """Map an election config and its stored result on the protocol view.

    The erasure of a candidate (``protocol.erasure``) also calls it, with the config
    before and after the change.
    """
    elected = set(result.elected) if result is not None else set()
    names = {c.id: c.name for c in election.candidates}
    counts = result.counts if result is not None else {}
    listed = [
        ElectionLine(name=c.name, votes=counts.get(c.id, 0), elected=c.id in elected)
        for c in election.candidates
    ]
    by_votes = result is not None and result.yes is None
    lines = sorted(listed, key=lambda line: -line.votes) if by_votes else listed
    lot = result.lot if result is not None else None
    runoff = result.runoff if result is not None else None
    return ElectionSnippet(
        question=(question or "Wahlgang").strip() or "Wahlgang",
        seats=election.seats,
        round=round_,
        candidates=lines,
        abstentions=result.abstentions if result is not None else 0,
        yes=result.yes if result is not None else None,
        no=result.no if result is not None else None,
        by_lot=lot is not None and lot.drawn is not None,
        lot_pending=lot is not None and lot.drawn is None,
        runoff_names=[names.get(cid, cid) for cid in runoff.candidate_ids] if runoff else [],
        runoff_seats=runoff.seats if runoff else 0,
        closed=result is not None,
        attempt=attempt,
    )


_WEEKDAYS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")


def poll_option_label(option: PollOption, tz: ZoneInfo) -> str:
    """Return the label of a poll option: its text, or „Di, 3.11. · 18:00–20:00“."""
    return (
        option.label or option.id
        if option.start is None
        else _date_label(option.start, option.end, tz)
    )


def _date_label(start_at: datetime, end_at: datetime | None, tz: ZoneInfo) -> str:
    """Return the label of a date option: „Di, 3.11. · 18:00“, with the end when set."""
    start = start_at.astimezone(tz)
    end = f"–{end_at.astimezone(tz):%H:%M}" if end_at is not None else ""
    return f"{_WEEKDAYS[start.weekday()]}, {start.day}.{start.month}. · {start:%H:%M}{end}"


def poll_meta(config: PollConfig) -> str:
    """Return the kind line of a poll snippet."""
    match (config.mode, config.max_choices):
        case ("date", _):
            return "Terminumfrage"
        case ("single", _):
            return "Umfrage · Einzelwahl"
        case (_, None):
            return "Umfrage · Mehrfachwahl"
        case (_, most):
            return f"Umfrage · Mehrfachwahl, höchstens {most}"


def poll_snippet_of(
    config: PollConfig, result: PollResultOut | None, *, question: str | None, tz: ZoneInfo
) -> PollSnippet:
    """Map a poll and its stored result on the protocol view (highest first)."""
    labels = {o.id: poll_option_label(o, tz) for o in config.options}
    date = config.mode == "date"
    return PollSnippet(
        question=(question or "Umfrage").strip() or "Umfrage",
        meta=poll_meta(config),
        lines=_poll_lines(result, labels, date=date) if result is not None else [],
        abstentions=None if date else (result.abstentions if result is not None else 0),
        ballots=result.ballots if result is not None else 0,
        date=date,
        closed=result is not None,
    )


def _poll_lines(
    result: PollResultOut, labels: Mapping[str, str], *, date: bool
) -> list[PollLine]:
    """Map the stored result of a poll on its option lines, in the stored order."""
    order = [oid for oid in result.order if oid in labels] or list(labels)
    top = frozenset(result.top)
    return [
        PollLine(
            label=labels[oid],
            count=result.counts.get(oid, 0),
            maybe=(result.maybe or {}).get(oid, 0) if date else None,
            top=oid in top,
        )
        for oid in order
    ]


def _guest_note(view: VoteOut) -> str | None:
    """Return the base line of a vote with guests, or None for a members vote."""
    return (
        guest_vote_note(
            view.tally.present_members,
            view.tally.present_guests,
            sum(view.tally.counts.values()),
        )
        if view.guests_vote
        else None
    )


def _vote_title(application_id: UUID | None, question: str | None = None) -> str:
    """Build the snippet heading of an embedded vote.

    For an application item, the heading is a short reference to the application. For
    a generic decision question without an application, the heading is the question
    itself. The protokollant can edit the heading in the editor.
    """
    plain = question.strip() if question and question.strip() else "Beschlussfrage"
    return f"Abstimmung – Antrag {str(application_id)[:8]}" if application_id is not None else plain
