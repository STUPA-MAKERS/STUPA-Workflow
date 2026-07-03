"""Protocol service.

Bound to an ``AsyncSession``; drives the protocol lifecycle:

* :meth:`get_or_create` — create or load a meeting's protocol (idempotent via
  UNIQUE ``meeting_id``); takes ``gremium_id``/``cd_variant`` from meeting+gremium.
* :meth:`update_markdown` — update the editor body (draft only).
* :meth:`embed_votes` — append votes as Markdown snippets + write
  ``protocol_vote_ref`` (idempotent: already-referenced votes are skipped).
* :meth:`finalize` — Markdown → pytex → PDF → MinIO → mail to
  MAIL_LIST(gremium); ``status='final'`` + ``sent_at``.

Reuses the pytex client, object storage and mail queue from
:mod:`app.modules.pdf` / :mod:`app.modules.notifications` unchanged.

Failure discipline: if storage is deliberately off (dev/demo without MinIO),
``finalize`` still completes (``final`` + mail without PDF link). If an
EXISTING render/storage backend fails transiently, the service raises
:class:`ServiceUnavailableError` (503) → the session dependency rolls back,
the protocol stays draft and the call is repeatable.
"""

from __future__ import annotations

from datetime import UTC, datetime
from datetime import time as _time
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.gremium_roles import gremium_ids_with_permission
from app.modules.admin.models import Gremium, GremiumMembership, MailList
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
    """Deterministic MinIO key (own ``pdf/protocol/`` prefix)."""
    return f"pdf/protocol/{protocol_id}.pdf"


def protocol_public_storage_key(protocol_id: UUID) -> str:
    """MinIO key of the redacted public protocol variant."""
    return f"pdf/protocol/{protocol_id}-public.pdf"


# Placeholder for the body of non-public agenda items in the public PDF
# (numbering stays, the content is redacted).
_NON_PUBLIC_PLACEHOLDER = "*(nicht-öffentlicher Tagesordnungspunkt)*"
# Neutral heading for non-public items in the public PDF: the original title
# may encode the sensitive subject and must not reach the mailed variant.
_NON_PUBLIC_HEADING = "Nicht-öffentlicher Tagesordnungspunkt"


class ProtocolService:
    """Protocol operations + finalization over the shared render infrastructure."""

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

    # ----------------------------------------------------------------- helpers
    async def _get(self, protocol_id: UUID) -> Protocol:
        protocol = (
            await self.session.execute(
                select(Protocol).where(Protocol.id == protocol_id)
            )
        ).scalar_one_or_none()
        if protocol is None:
            raise NotFoundError(f"protocol {protocol_id} not found")
        return protocol

    # --------------------------------------------------------- authz (per gremium)
    # The protocol assembles the per-item bodies that the live stack already
    # authorizes PER GREMIUM (assigned protokollant + gremium roles with
    # ``session.manage``/``protocol.write``). Global ``meeting.manage`` alone
    # would lock those users out, so we delegate to ``MeetingService`` —
    # identical scope rules to ``/api/meetings/…``.
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
        """Check write access to a meeting's protocol (create/load).

        Manager (``meeting.manage``/gremium ``session.manage``), assigned
        protokollant OR gremium role with ``protocol.write`` — like ``can_write``."""
        meeting = await self._meeting(meeting_id)
        if not await self._meeting_service().can_write(meeting, principal):
            raise ForbiddenError("not allowed to write this meeting's minutes")

    async def authorize_write(self, protocol_id: UUID, principal: Principal) -> None:
        """Check write access to an existing protocol (PATCH / embed votes)."""
        protocol = await self._get(protocol_id)
        await self.authorize_write_meeting(protocol.meeting_id, principal)

    async def authorize_finalize(self, protocol_id: UUID, principal: Principal) -> None:
        """Finalize+send requires write access AND ``protocol.finalize``
        (global OR as a gremium role of this gremium). Stricter than draft writing."""
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
        """Check read access: same visibility as the meeting (``assert_can_read``)."""
        protocol = await self._get(protocol_id)
        await self._meeting_service().assert_can_read(protocol.meeting_id, principal)

    async def authorize_read_meeting(
        self, meeting_id: UUID, principal: Principal
    ) -> None:
        """Check read access to a meeting's protocol (GET …/protocol)."""
        await self._meeting_service().assert_can_read(meeting_id, principal)

    def _pdf_path(self, protocol: Protocol) -> str | None:
        """App-relative PDF path (reachable via nginx /api/, never a bucket link).

        MinIO sits on the internal network without a published port; an
        S3v4-signed URL binds the internal host into the signature → unreachable
        from the browser. The ``/pdf`` endpoint streams the bytes server-side."""
        if protocol.pdf_storage_key is not None and self.storage is not None:
            return f"/api/protocols/{protocol.id}/pdf"
        return None

    def _public_pdf_path(self, protocol: Protocol) -> str | None:
        """App-relative path of the redacted public variant."""
        if protocol.public_pdf_storage_key is not None and self.storage is not None:
            return f"/api/protocols/{protocol.id}/pdf/public"
        return None

    async def get_pdf_bytes(self, protocol_id: UUID) -> bytes:
        """Fetch the protocol's PDF bytes from storage (for the ``/pdf`` stream).

        404 if the protocol is missing, no PDF is rendered yet, or storage is
        off. Transient storage errors → 503 (repeatable)."""
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
        """Fetch the redacted public variant's bytes (for the ``/pdf/public`` stream)."""
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

    # ------------------------------------------------------------- get/create
    async def _by_meeting(self, meeting_id: UUID) -> Protocol | None:
        return (
            await self.session.execute(
                select(Protocol).where(Protocol.meeting_id == meeting_id)
            )
        ).scalar_one_or_none()

    @staticmethod
    def _insert_values(
        meeting: Meeting, gremium: Gremium | None, author: str | None
    ) -> dict[str, object]:
        """Column values of a fresh ``protocol`` row (``cd_variant`` from the gremium)."""
        return {
            "meeting_id": meeting.id,
            "gremium_id": meeting.gremium_id,
            "markdown": "",
            "status": "draft",
            "author": author,
            "cd_variant": gremium.cd_variant if gremium is not None else None,
        }

    async def get_by_meeting(self, meeting_id: UUID) -> ProtocolOut:
        """Read the meeting's protocol (404 without one) — reload/poll path.

        Deliberately without a create side effect: the frontend polls during
        the background render; a GET is not subject to the write rate limit."""
        protocol = await self._by_meeting(meeting_id)
        if protocol is None:
            raise NotFoundError(f"protocol for meeting {meeting_id} not found")
        return self._to_out(protocol)

    async def get_or_create(
        self, meeting_id: UUID, *, author: str | None = None
    ) -> ProtocolOut:
        """Create or load the meeting's protocol (idempotent). 404 without a meeting.

        Race-safe: on a parallel POST, ``INSERT … ON CONFLICT (meeting_id) DO
        NOTHING`` avoids the UNIQUE violation (no ``IntegrityError`` → no 500);
        the following re-select returns the same row in BOTH cases (created
        here or won by the parallel request)."""
        existing = await self._by_meeting(meeting_id)
        if existing is not None:
            return self._to_out(existing)

        meeting = await self.session.get(Meeting, meeting_id)
        if meeting is None:
            raise NotFoundError(f"meeting {meeting_id} not found")
        # The protocol is created only when the meeting starts (planned→live),
        # never manually in advance: no minutes before the start.
        if meeting.status == "planned":
            raise ConflictError(
                "the meeting has not started — its minutes are created on start"
            )
        gremium = await self.session.get(Gremium, meeting.gremium_id)
        await self.session.execute(
            pg_insert(Protocol)
            .values(**self._insert_values(meeting, gremium, author))
            .on_conflict_do_nothing(constraint="uq_protocol_meeting")
        )
        await self.session.commit()

        protocol = await self._by_meeting(meeting_id)
        if protocol is None:  # only if the row vanished between insert+select
            raise NotFoundError(f"protocol for meeting {meeting_id} not found")
        return self._to_out(protocol)

    # --------------------------------------------------------------- markdown
    async def update_markdown(self, protocol_id: UUID, markdown: str) -> ProtocolOut:
        """Update the editor body. 409 if the protocol is already final."""
        protocol = await self._get(protocol_id)
        self._ensure_draft(protocol)
        protocol.markdown = markdown
        await self.session.flush()
        await self.session.commit()
        return self._to_out(protocol)

    # ----------------------------------------------------------------- votes
    async def embed_votes(
        self, protocol_id: UUID, vote_ids: list[UUID]
    ) -> ProtocolOut:
        """Append votes as snippets + write ``protocol_vote_ref`` (idempotent)."""
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
                continue  # already embedded → no duplicate snippet
            await self._get_vote(vote_id)  # 404 + avoids FK IntegrityError on insert
            already.add(vote_id)
            # Race-safe: ON CONFLICT (protocol_id, vote_id) DO NOTHING. If a
            # parallel request wrote the ref first, RETURNING yields nothing →
            # no duplicate snippet (idempotent, no IntegrityError/500).
            inserted = (
                await self.session.execute(
                    pg_insert(ProtocolVoteRef)
                    .values(protocol_id=protocol_id, vote_id=vote_id)
                    .on_conflict_do_nothing(constraint="uq_protocol_vote_ref")
                    .returning(ProtocolVoteRef.id)
                )
            ).first()
            if inserted is None:
                continue  # concurrently embedded already
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

    # -------------------------------------------------------------- finalize
    async def start_finalize(self, protocol_id: UUID) -> tuple[ProtocolOut, bool]:
        """Start finalization: ``draft → rendering`` (committed, non-blocking).

        The caller (router) then enqueues the ``render_protocol`` worker job.
        Idempotent: an already ``rendering``/``final`` protocol is returned
        unchanged — the second tuple element ``False`` means "do not enqueue"
        (no double render, no double send)."""
        protocol = await self._get(protocol_id)
        if protocol.status in ("rendering", "final"):
            return self._to_out(protocol), False
        protocol.status = "rendering"
        await self.session.flush()
        await self.session.commit()
        return self._to_out(protocol), True

    async def revert_to_draft(self, protocol_id: UUID) -> None:
        """Roll back ``rendering → draft`` after a permanent render/send failure.

        The protocol stays re-finalizable and never hangs in ``rendering``;
        an already final protocol is untouched."""
        protocol = await self._get(protocol_id)
        if protocol.status == "rendering":
            protocol.status = "draft"
            await self.session.flush()
            await self.session.commit()

    async def finalize(self, protocol_id: UUID, *, now: datetime) -> ProtocolOut:
        """Render Markdown → PDF → MinIO → mail to MAIL_LIST(gremium); ``final``.

        Runs in the worker (``render_protocol``, status ``rendering``) OR
        synchronously as fallback without Redis (status still ``draft``).
        Idempotent: an already final protocol is returned unchanged — no second
        render, no double send."""
        protocol = await self._get(protocol_id)
        if protocol.status == "final":
            return self._to_out(protocol)

        # The pytex render runs BEFORE the commit: a permanent compile error
        # (4xx) or a transient pytex outage (5xx) rolls the session back and
        # the protocol stays draft. The storage ``put`` and the mail enqueue
        # deliberately happen only AFTER a successful commit: if the commit
        # failed, we would otherwise leave an orphaned MinIO object and an
        # enqueued send job for a row that never became ``final``.
        # ``_render_pdf`` only sets the key columns + returns the bytes; the
        # upload happens post-commit in ``_store``.
        uploads: list[tuple[str, bytes]] = []
        if await self._has_non_public(protocol.meeting_id):
            # Dual render: full internal PDF + redacted public PDF. Only the
            # public variant is mailed (non-public items must not reach the list).
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
        # From here the DB state is persistent — side effects are safe now.
        await self._store(uploads)
        await self._send(protocol, mail_pdf)
        return self._to_out(protocol)

    # ----------------------------------------------------------- finalize bits
    async def _build_document(self, protocol: Protocol, *, public: bool = False) -> str:
        meeting = await self.session.get(Meeting, protocol.meeting_id)
        gremium = await self.session.get(Gremium, protocol.gremium_id)
        title = meeting.title if meeting is not None else "Protokoll"
        # Source of truth is the per-item editor (agenda). If items exist, the
        # protocol is assembled from their Markdown bodies + decision snippets;
        # otherwise fall back to the freely edited ``protocol.markdown``.
        # ``public=True`` redacts non-public items.
        assembled = await self._assemble_from_agenda(protocol.meeting_id, public=public)
        # ``public=True`` also redacts the header metadata: the mailed variant
        # must not carry attendee/absentee names or the protokollant's name.
        # ``_header_meta`` then returns empty name lists + counters only (as
        # data lines); the counter-based quorum statement stays meaningful.
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
        """Convert ``meeting.closed_at`` (UTC) to local time for the end line."""
        if not isinstance(closed_at, datetime):
            return None
        settings = self.settings or get_settings()
        tz = ZoneInfo(settings.local_timezone)
        return closed_at.astimezone(tz).time().replace(second=0, microsecond=0)

    async def _quorate(self, gremium: object | None, present_count: int) -> bool | None:
        """Compute quorum: present vs. active members.

        Threshold = ``gremium.quorum_percent`` if set, else "more than half".
        ``None`` without gremium/members — then no statement in the PDF."""
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
        """Resolve protokollant + attendance lists (name or sub) for the header.

        Returns ``(protokollant, present, absent, present_count, datalines)``.
        ``present_count`` is the true number of attendees (source for the
        quorum) even when ``public=True`` suppresses the name lists.

        ``public=True`` redacts person-related header metadata for the mailed
        variant: full attendance lists and the protokollant's name must not go
        external. Only the counters are emitted as data lines
        (``Anwesend: n`` / ``Abwesend: n``)."""
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
            # Keep names + protokollant out; keep only the counters as data lines.
            datalines = [
                f"Anwesend: {present_count}",
                f"Abwesend: {len(absent)}",
            ]
            return None, [], [], present_count, datalines
        return protokollant, present, absent, present_count, []

    async def _has_non_public(self, meeting_id: UUID) -> bool:
        """Return True if the meeting has a non-public agenda item (drives dual render)."""
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
        """Build the protocol Markdown from agenda-item bodies + their decision votes.

        ``public=True`` redacts non-public items: the heading (and thus the
        numbering) stays, body + decision snippets are replaced by a placeholder."""
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
            # Top-level ``#`` WITHOUT a "TOP n:" prefix: pytex numbers the
            # sections itself as "TOP 1", "TOP 2", … — ``##`` would be numbered
            # "TOP 0.1" and a manual prefix would appear twice.
            if public and item.non_public:
                # The original title may encode the sensitive subject and must
                # not reach the mailed public variant. Neutral heading +
                # redacted content; numbering stays stable.
                block = [f"# {_NON_PUBLIC_HEADING}", _NON_PUBLIC_PLACEHOLDER]
                blocks.append("\n\n".join(block))
                continue
            block = [f"# {heading}"]
            if item.body and item.body.strip():
                # Demote body headings one level: only the item heading stays
                # top-level (otherwise every ``#`` would count as its own TOP).
                block.append(demote_headings(item.body.strip()))
            votes = (
                await self.session.execute(
                    select(Vote)
                    .where(
                        Vote.agenda_item_id == item.id,
                        # Cancelled votes have no result — no empty tally box.
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
        """Render pytex → PDF bytes (BEFORE the commit). Sets the key column but
        does NOT upload — the storage ``put`` runs post-commit in :meth:`_store`.

        ``public=True`` sets ``public_pdf_storage_key`` instead of
        ``pdf_storage_key``. With storage off (dev) nothing is rendered
        (``None``); a permanent pytex error → 400, a transient one → 503
        (the draft survives)."""
        # Storage is the deliberate on/off switch: without it, finalize
        # proceeds without a PDF (demo/contract CI without MinIO).
        if self.storage is None or self.pytex is None:
            return None
        try:
            variant = protocol_variant_for(protocol.cd_variant)
            # RCE protection: the user-written body could carry pytex's
            # Markdown ``eval`` escape (``[//]: # "EXPR"`` → eval in the
            # container). ``sanitize_user_markdown`` removes it UNCONDITIONALLY
            # during assembly (``build_protocol_document``) before the Markdown
            # reaches pytex; ``\write18`` shell escape does not apply under
            # tectonic. This path therefore renders ``trusted`` (client
            # default): the protocol variant needs pytex's template machinery,
            # which ``untrusted``/``sandboxed`` blocks (untrusted failed every
            # protocol render with 400). As a second, independent line,
            # ``PytexClient.render_pdf`` structurally verifies before the
            # trusted render that no eval trigger survived — a sanitizer bypass
            # becomes a contained error instead of RCE.
            pdf = await self.pytex.render_pdf(markdown, variant=variant)
        except PytexError as exc:
            # 4xx = permanent input/compile error (e.g. invalid LaTeX): no
            # retry, show the (scrubbed) reason instead of a misleading 503.
            # 5xx/transport stays transient.
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
        """Upload rendered PDFs to object storage AFTER a successful commit.

        Only now is the MinIO object created — a failed commit leaves no
        orphaned object. With storage off, ``uploads`` is empty (``_render_pdf``
        returned ``None``). A transient storage error → 503: the protocol is
        already committed ``final``, so a repeated ``finalize`` is a no-op via
        the ``status=='final'`` idempotency."""
        if self.storage is None:
            return
        try:
            for key, pdf in uploads:
                await self.storage.put(key, pdf, "application/pdf")
        except StorageError as exc:
            # Existing backend transiently unreachable → 503. No path leak.
            raise ServiceUnavailableError(
                "Protocol rendering temporarily unavailable."
            ) from exc

    async def _send(self, protocol: Protocol, pdf: bytes | None) -> None:
        """Mail the protocol to MAIL_LIST(gremium) — idempotent key, PDF attached.

        Subject/body name gremium + meeting; the HTML version uses the branded
        mail layout. Deliberately no link: the former
        ``/api/protocols/{id}/pdf`` link required login + ``meeting.manage``
        and was broken for members and external list addresses."""
        if self.mail_queue is None:
            return
        recipients = await self._recipients(protocol.gremium_id)
        # Respect opted-out protocol mails.
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
        """Build the flat, deduplicated recipient list of the gremium.

        UNION of active gremium members (term window, email≠NULL) and the
        configured extra lists (``mail_list``) — the extra addresses receive
        the protocol in addition to, not instead of, the members."""
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

    # ------------------------------------------------------------------ utils
    @staticmethod
    def _ensure_draft(protocol: Protocol) -> None:
        if protocol.status == "final":
            raise ConflictError(
                "Protocol is finalized and read-only.", code="conflict"
            )
        if protocol.status == "rendering":
            # Content is frozen during the background render — the PDF would
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

    Application item: short reference to the application. Generic decision
    question (no application): the question itself. The protokollant can edit
    the heading freely in the editor."""
    if application_id is not None:
        return f"Abstimmung – Antrag {str(application_id)[:8]}"
    return question.strip() if question and question.strip() else "Beschlussfrage"
