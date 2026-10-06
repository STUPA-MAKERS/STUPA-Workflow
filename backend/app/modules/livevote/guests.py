"""Public meeting with a QR code (#17): join requests, guests and their view.

A person without an account scans the QR code, enters a name and asks to join. The
meeting lead admits or rejects the request. An admitted guest follows the public
agenda items like a member and, when the meeting lets guests vote, votes in the votes
with ``guestsVote``.

Rules that this module enforces:

* One device, one token. The token is random, lives in an HttpOnly cookie, and the
  table keeps only its SHA-256 hash. A second request of the same device replaces the
  first one.
* A rejected or removed guest may ask again 3 minutes after the decision; before that
  the server answers 429 with ``Retry-After``.
* The guest view never holds the name of another person, the attendance list, a
  delegation, or the content of a non-public agenda item. A non-public item shows its
  title only (decision 2026-10-06).
* The audit log stores the guest id only, never the name: the chain is append-only.
* Privacy: the close of the meeting deletes the requests that never got admitted and
  every token hash. Leaving or withdrawing replaces the own name with the pseudonym
  "Gast n" at once. The finalization of the protocol pseudonymizes all guests.

The lead routes need ``session.manage`` in the gremium of the meeting (the router
checks it). The public routes authenticate the guest by the token alone.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import Gremium
from app.modules.applications.models import Application
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.livevote.agenda_service import agenda_order, title_of
from app.modules.livevote.events import GuestEventReason
from app.modules.livevote.models import (
    Meeting,
    MeetingAgendaItem,
    MeetingAttendance,
    MeetingGuest,
)
from app.modules.livevote.public_schemas import (
    GuestAgendaItem,
    GuestMe,
    GuestTally,
    GuestView,
    GuestVote,
    PublicMeetingHead,
)
from app.modules.livevote.schemas import JoinLinkOut, MeetingGuestOut, QrMatrixOut
from app.modules.voting.models import Vote
from app.modules.voting.schemas import BallotAccepted
from app.modules.voting.service import VotingService, guest_voter_sub
from app.shared.config_schemas import VoteConfig
from app.shared.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    RateLimitedError,
    UnauthorizedError,
)

if TYPE_CHECKING:
    from app.modules.livevote.service.pubsub import BrokerPublisher

logger = logging.getLogger("app.livevote.guests")

# The code alphabet leaves out 0/O, 1/I/L: a person types the code from the beamer.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 6
# A rejected or removed guest may ask again after this time (decision #17).
RETRY_AFTER = timedelta(minutes=3)
# The own state refreshes `last_seen_at` at most once in this interval.
_SEEN_INTERVAL = timedelta(seconds=60)
_CODE_ATTEMPTS = 20


def new_join_code() -> str:
    """Return a random join code of `CODE_LENGTH` characters."""
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def normalize_code(code: str) -> str:
    """Normalize a typed code: upper case, without blanks and dashes (`7kq-4mp`)."""
    return "".join(ch for ch in code.upper() if ch not in " -")


def new_token() -> str:
    """Return a new device token (256 bits of entropy)."""
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> bytes:
    """Return the SHA-256 hash of a device token. Only the hash goes to the database."""
    return hashlib.sha256(token.encode("utf-8")).digest()


def qr_matrix(text: str) -> QrMatrixOut:
    """Encode `text` as a QR code and return its module matrix without the quiet zone.

    The QR code comes from `segno` (BSD-3-Clause, pure Python, no dependencies). The
    error correction level M survives a little glare on a projector.
    """
    import segno

    qr = segno.make(text, error="m", micro=False)
    rows = ["".join("1" if dark else "0" for dark in row) for row in qr.matrix_iter(border=0)]
    return QrMatrixOut(size=len(rows), rows=rows)


@dataclass
class GuestEvents:
    """The broadcasts that a change produces. The caller sends them after the commit."""

    requested: list[MeetingGuestOut] = field(default_factory=list)
    updated: list[tuple[MeetingGuestOut, GuestEventReason | None]] = field(default_factory=list)
    counts: bool = False


class GuestService:
    """Join requests and guests of public meetings, on one `AsyncSession`."""

    def __init__(
        self,
        session: AsyncSession,
        publisher: BrokerPublisher | None = None,
        *,
        base_url: str = "",
    ) -> None:
        self.session = session
        self.publisher = publisher
        self.base_url = base_url.rstrip("/")

    # -- shared helpers -----------------------------------------------------------

    async def _meeting(self, meeting_id: UUID, *, for_update: bool = False) -> Meeting:
        stmt = select(Meeting).where(Meeting.id == meeting_id)
        if for_update:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        meeting = (await self.session.execute(stmt)).scalar_one_or_none()
        if meeting is None:
            raise NotFoundError(f"meeting {meeting_id} not found")
        return meeting

    async def _guest(
        self, meeting_id: UUID, guest_id: UUID, *, for_update: bool = False
    ) -> MeetingGuest:
        stmt = select(MeetingGuest).where(
            MeetingGuest.id == guest_id, MeetingGuest.meeting_id == meeting_id
        )
        if for_update:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        guest = (await self.session.execute(stmt)).scalar_one_or_none()
        if guest is None:
            raise NotFoundError(f"guest {guest_id} not found", code="guest_not_found")
        return guest

    @staticmethod
    def _assert_open(meeting: Meeting) -> None:
        """Require a meeting that is not closed and has public participation on."""
        if meeting.status == "closed":
            raise ConflictError("The meeting is closed.", code="meeting_closed")
        if not meeting.public_join:
            raise ConflictError(
                "Public participation is off for this meeting.", code="meeting_not_public"
            )

    async def _names(self, principal_ids: set[UUID]) -> dict[UUID, str | None]:
        if not principal_ids:
            return {}
        rows = (
            await self.session.execute(
                select(PrincipalRow.id, PrincipalRow.display_name, PrincipalRow.email).where(
                    PrincipalRow.id.in_(principal_ids)
                )
            )
        ).all()
        return {pid: (name or email) for pid, name, email in rows}

    async def _outs(self, guests: Sequence[MeetingGuest]) -> list[MeetingGuestOut]:
        names = await self._names({g.decided_by for g in guests if g.decided_by is not None})
        return [self._out(g, names.get(g.decided_by) if g.decided_by else None) for g in guests]

    @staticmethod
    def _out(
        guest: MeetingGuest, decided_by_name: str | None = None, *, status: str | None = None
    ) -> MeetingGuestOut:
        return MeetingGuestOut(
            id=guest.id,
            number=guest.seq,
            displayName=guest.display_name,
            status=status or guest.status,  # type: ignore[arg-type]
            requestedAt=guest.requested_at,
            decidedAt=guest.decided_at,
            decidedByName=decided_by_name,
            admittedAt=guest.admitted_at,
        )

    async def _principal_id(self, sub: str) -> UUID | None:
        return await self.session.scalar(select(PrincipalRow.id).where(PrincipalRow.sub == sub))

    async def counts(self, meeting_id: UUID) -> tuple[int, int]:
        """Return the admitted and the pending guests of a meeting."""
        rows = (
            await self.session.execute(
                select(MeetingGuest.status, func.count())
                .where(
                    MeetingGuest.meeting_id == meeting_id,
                    MeetingGuest.status.in_(("admitted", "pending")),
                )
                .group_by(MeetingGuest.status)
            )
        ).all()
        by_status = dict(rows)
        return by_status.get("admitted", 0), by_status.get("pending", 0)

    async def publish(self, meeting_id: UUID, events: GuestEvents) -> None:
        """Send the broadcasts of a committed change (best effort, a fault only logs)."""
        if self.publisher is None:
            return
        try:
            for guest in events.requested:
                await self.publisher.guest_requested(meeting_id, guest)
            for guest, reason in events.updated:
                await self.publisher.guest_updated(meeting_id, guest, reason)
            if events.counts or events.requested or events.updated:
                meeting = await self._meeting(meeting_id)
                admitted, pending = await self.counts(meeting_id)
                await self.publisher.guest_counts(
                    meeting_id,
                    public_join=meeting.public_join,
                    guests_mode=meeting.guests_mode,  # type: ignore[arg-type]
                    join_code=meeting.join_code,
                    admitted=admitted,
                    pending=pending,
                )
        except Exception:  # noqa: BLE001 - the broadcast is best effort
            logger.warning("guest broadcast failed (meeting=%s)", meeting_id)

    async def _audit(
        self, action: AuditAction, *, actor: str, meeting: Meeting, **data: object
    ) -> None:
        """Write a guest audit entry with ids and counts only, never a name."""
        await audit_record(
            self.session,
            actor=actor,
            action=action,
            target_type="meeting",
            target_id=str(meeting.id),
            data={"meetingId": str(meeting.id), "gremiumId": str(meeting.gremium_id), **data},
        )

    # -- meeting settings (called by the meeting lifecycle, no commit) ----------------

    async def ensure_code(self, meeting: Meeting) -> None:
        """Give the meeting a join code when it has none."""
        if meeting.join_code is None:
            await self.assign_code(meeting)

    async def assign_code(self, meeting: Meeting) -> str:
        """Give the meeting a new free join code, safe against a parallel collision.

        A parallel meeting can take the same code between the check and the write. The
        flush in a SAVEPOINT meets the unique index then, and the method takes another
        code instead of a 500. The meeting must be in the session.
        """
        for _ in range(_CODE_ATTEMPTS):
            code = await self._free_code()
            meeting.join_code = code
            try:
                async with self.session.begin_nested():
                    await self.session.flush()
            except IntegrityError:
                continue
            return code
        raise ConflictError("No free join code; try again.", code="join_code_exhausted")

    async def _free_code(self) -> str:
        """Return a code that no open meeting uses."""
        for _ in range(_CODE_ATTEMPTS):
            code = new_join_code()
            taken = await self.session.scalar(
                select(Meeting.id).where(Meeting.join_code == code, Meeting.status != "closed")
            )
            if taken is None:
                return code
        raise ConflictError("No free join code; try again.", code="join_code_exhausted")

    async def _void_pending(
        self, meeting: Meeting, events: GuestEvents, reason: GuestEventReason
    ) -> int:
        """Delete the open requests of the meeting: they are no longer valid."""
        pending = (
            (
                await self.session.execute(
                    select(MeetingGuest)
                    .where(MeetingGuest.meeting_id == meeting.id, MeetingGuest.status == "pending")
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        for guest in pending:
            events.updated.append((self._out(guest, status="expired"), reason))
            await self.session.delete(guest)
        await self.session.flush()
        return len(pending)

    async def switch_off(self, meeting: Meeting, *, actor_sub: str, now: datetime) -> GuestEvents:
        """Public participation goes off: void the requests and remove the guests.

        The cast ballots of the removed guests stay counted. The caller commits.
        """
        events = GuestEvents(counts=True)
        await self._void_pending(meeting, events, "public_off")
        actor_id = await self._principal_id(actor_sub)
        admitted = (
            (
                await self.session.execute(
                    select(MeetingGuest)
                    .where(MeetingGuest.meeting_id == meeting.id, MeetingGuest.status == "admitted")
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        for guest in admitted:
            guest.status = "removed"
            guest.decided_at = now
            guest.decided_by = actor_id
        await self.session.flush()
        for out in await self._outs(admitted):
            events.updated.append((out, "public_off"))
        return events

    async def purge_on_close(self, meeting: Meeting) -> GuestEvents:
        """The meeting closes: delete the requests and pseudonymize the guests (#17).

        The rows that never got admitted go: the rejected, the withdrawn and the still
        open requests. The names of the admitted guests go too (decision 2026-10-06:
        at the latest at the close); the numbers stay for the protocol. Every token
        hash goes, because a token has no use after the close. The caller commits and
        then sends the returned events: the lead list drops the deleted rows, and the
        socket of a waiting device ends.

        Returns:
            The broadcasts for the deleted rows (status ``expired``, reason
            ``meeting_closed``).
        """
        events = GuestEvents(counts=True)
        gone = (
            (
                await self.session.execute(
                    select(MeetingGuest).where(
                        MeetingGuest.meeting_id == meeting.id,
                        MeetingGuest.admitted_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        for guest in gone:
            events.updated.append((self._out(guest, status="expired"), "meeting_closed"))
        await self.session.execute(
            delete(MeetingGuest).where(
                MeetingGuest.meeting_id == meeting.id, MeetingGuest.admitted_at.is_(None)
            )
        )
        await self.session.execute(
            update(MeetingGuest)
            .where(MeetingGuest.meeting_id == meeting.id)
            .values(token_hash=None, display_name=None)
        )
        return events

    async def pseudonymize(self, meeting_id: UUID) -> int:
        """Replace every guest name of the meeting with "Gast 1 … n" (#17).

        The protocol finalization calls this. The numbers follow the order of the
        admission. The token hashes go too. The caller commits.

        Returns:
            The number of guests.
        """
        guests = (
            (
                await self.session.execute(
                    select(MeetingGuest)
                    .where(MeetingGuest.meeting_id == meeting_id)
                    .order_by(
                        MeetingGuest.admitted_at.asc().nulls_last(),
                        MeetingGuest.requested_at,
                        MeetingGuest.id,
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        for number, guest in enumerate(guests, start=1):
            guest.seq = number
            guest.display_name = None
            guest.token_hash = None
        await self.session.flush()
        return len(guests)

    async def attended_count(self, meeting_id: UUID) -> int:
        """Return the guests who took part (admitted at some point), for the protocol."""
        return (
            await self.session.scalar(
                select(func.count())
                .select_from(MeetingGuest)
                .where(MeetingGuest.meeting_id == meeting_id, MeetingGuest.admitted_at.is_not(None))
            )
        ) or 0

    # -- the meeting lead ---------------------------------------------------------------

    async def list(self, meeting_id: UUID) -> list[MeetingGuestOut]:
        """List the guests: the open requests first, then the others."""
        await self._meeting(meeting_id)
        guests = (
            (
                await self.session.execute(
                    select(MeetingGuest)
                    .where(MeetingGuest.meeting_id == meeting_id)
                    .order_by(
                        (MeetingGuest.status != "pending").asc(),
                        func.coalesce(MeetingGuest.admitted_at, MeetingGuest.requested_at),
                        MeetingGuest.seq,
                    )
                )
            )
            .scalars()
            .all()
        )
        return await self._outs(guests)

    async def _decide(
        self,
        meeting_id: UUID,
        guest_id: UUID,
        *,
        actor_sub: str,
        expect: str,
        to: str,
        action: AuditAction,
    ) -> MeetingGuestOut:
        meeting = await self._meeting(meeting_id, for_update=True)
        self._assert_open(meeting)
        guest = await self._guest(meeting_id, guest_id, for_update=True)
        if guest.status != expect:
            raise ConflictError(
                f"The guest is {guest.status}.",
                code="guest_not_pending" if expect == "pending" else "guest_not_admitted",
            )
        now = datetime.now(UTC)
        guest.status = to
        guest.decided_at = now
        guest.decided_by = await self._principal_id(actor_sub)
        if to == "admitted":
            guest.admitted_at = now
        await self._audit(action, actor=actor_sub, meeting=meeting, guestId=str(guest.id))
        await self.session.flush()
        out = (await self._outs([guest]))[0]
        await self.session.commit()
        await self.publish(meeting_id, GuestEvents(updated=[(out, None)]))
        return out

    async def admit(self, meeting_id: UUID, guest_id: UUID, *, actor_sub: str) -> MeetingGuestOut:
        """Admit a waiting guest. A vote that is open already counts the guest too."""
        return await self._decide(
            meeting_id,
            guest_id,
            actor_sub=actor_sub,
            expect="pending",
            to="admitted",
            action=AuditAction.GUEST_ADMITTED,
        )

    async def reject(self, meeting_id: UUID, guest_id: UUID, *, actor_sub: str) -> MeetingGuestOut:
        """Reject a waiting guest. The device may ask again after 3 minutes."""
        return await self._decide(
            meeting_id,
            guest_id,
            actor_sub=actor_sub,
            expect="pending",
            to="rejected",
            action=AuditAction.GUEST_REJECTED,
        )

    async def remove(self, meeting_id: UUID, guest_id: UUID, *, actor_sub: str) -> MeetingGuestOut:
        """Remove an admitted guest. The ballots that the guest cast stay counted."""
        return await self._decide(
            meeting_id,
            guest_id,
            actor_sub=actor_sub,
            expect="admitted",
            to="removed",
            action=AuditAction.GUEST_REMOVED,
        )

    async def rename(
        self, meeting_id: UUID, guest_id: UUID, name: str, *, actor_sub: str
    ) -> MeetingGuestOut:
        """Give a guest another name (for example an offensive one). Audit without names."""
        meeting = await self._meeting(meeting_id, for_update=True)
        self._assert_open(meeting)
        guest = await self._guest(meeting_id, guest_id, for_update=True)
        if guest.display_name is None:
            raise ConflictError(
                "The guest is pseudonymized; the name cannot change.",
                code="guest_pseudonymized",
            )
        guest.display_name = name
        await self._audit(
            AuditAction.GUEST_RENAMED, actor=actor_sub, meeting=meeting, guestId=str(guest.id)
        )
        await self.session.flush()
        out = (await self._outs([guest]))[0]
        await self.session.commit()
        await self.publish(meeting_id, GuestEvents(updated=[(out, None)]))
        return out

    async def admit_all(self, meeting_id: UUID, *, actor_sub: str) -> list[MeetingGuestOut]:
        """Admit every waiting guest at once."""
        meeting = await self._meeting(meeting_id, for_update=True)
        self._assert_open(meeting)
        guests = (
            (
                await self.session.execute(
                    select(MeetingGuest)
                    .where(MeetingGuest.meeting_id == meeting_id, MeetingGuest.status == "pending")
                    .order_by(MeetingGuest.requested_at, MeetingGuest.seq)
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        now = datetime.now(UTC)
        actor_id = await self._principal_id(actor_sub)
        for guest in guests:
            guest.status = "admitted"
            guest.decided_at = now
            guest.decided_by = actor_id
            guest.admitted_at = now
        if guests:
            await self._audit(
                AuditAction.GUEST_ADMIT_ALL,
                actor=actor_sub,
                meeting=meeting,
                count=len(guests),
                guestIds=[str(g.id) for g in guests],
            )
        await self.session.flush()
        outs = await self._outs(guests)
        await self.session.commit()
        await self.publish(meeting_id, GuestEvents(updated=[(o, None) for o in outs]))
        return outs

    def join_url(self, code: str) -> str:
        return f"{self.base_url}/j/{code}"

    def _link(self, code: str) -> JoinLinkOut:
        url = self.join_url(code)
        return JoinLinkOut(joinCode=code, joinUrl=url, qr=qr_matrix(url))

    async def join_link(self, meeting_id: UUID) -> JoinLinkOut:
        """Return the join link and its QR code (409 when the meeting is not public)."""
        meeting = await self._meeting(meeting_id)
        if not meeting.public_join or meeting.join_code is None:
            raise ConflictError(
                "Public participation is off for this meeting.", code="meeting_not_public"
            )
        return self._link(meeting.join_code)

    async def rotate(self, meeting_id: UUID, *, actor_sub: str) -> JoinLinkOut:
        """Replace the join code. The old link stops working, open requests are void.

        The admitted guests stay: their device token does not depend on the code.
        """
        meeting = await self._meeting(meeting_id, for_update=True)
        self._assert_open(meeting)
        code = await self.assign_code(meeting)
        events = GuestEvents(counts=True)
        voided = await self._void_pending(meeting, events, "rotated")
        await self._audit(
            AuditAction.MEETING_JOIN_CODE_ROTATED,
            actor=actor_sub,
            meeting=meeting,
            voidedRequests=voided,
        )
        await self.session.commit()
        await self.publish(meeting_id, events)
        return self._link(code)

    # -- the guest (public routes) ---------------------------------------------------------

    async def meeting_by_code(self, code: str, *, for_update: bool = False) -> Meeting:
        """Find the open public meeting of a join code.

        An unknown code, a meeting without public participation and a closed meeting
        all give the same 404, so nobody can probe the codes.

        Raises:
            NotFoundError: ``join_code_unknown``.
        """
        normalized = normalize_code(code)
        stmt = select(Meeting).where(
            Meeting.join_code == normalized,
            Meeting.status != "closed",
            Meeting.public_join.is_(True),
        )
        if for_update:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        meeting = (await self.session.execute(stmt)).scalar_one_or_none()
        if meeting is None:
            raise NotFoundError("Unknown join code.", code="join_code_unknown")
        return meeting

    async def head(self, code: str) -> PublicMeetingHead:
        return await self._head(await self.meeting_by_code(code))

    async def _head(self, meeting: Meeting) -> PublicMeetingHead:
        gremium_name = await self.session.scalar(
            select(Gremium.name).where(Gremium.id == meeting.gremium_id)
        )
        return PublicMeetingHead(
            code=meeting.join_code or "",
            title=meeting.title,
            gremiumName=gremium_name,
            date=meeting.date,
            startTime=meeting.start_time,
            status=meeting.status,  # type: ignore[arg-type]
            startedAt=meeting.started_at,
            guestsMode=meeting.guests_mode,  # type: ignore[arg-type]
        )

    async def _by_token(
        self, token: str | None, *, for_update: bool = False
    ) -> MeetingGuest | None:
        if not token:
            return None
        stmt = select(MeetingGuest).where(MeetingGuest.token_hash == token_hash(token))
        if for_update:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    @staticmethod
    def _retry_after(guest: MeetingGuest, now: datetime) -> int | None:
        """Seconds until a rejected or removed guest may ask again, else None."""
        if guest.status not in ("rejected", "removed") or guest.decided_at is None:
            return None
        remaining = (guest.decided_at + RETRY_AFTER - now).total_seconds()
        return max(0, int(remaining + 0.999))

    async def join(
        self, code: str, name: str, token: str | None, *, now: datetime
    ) -> tuple[GuestMe, str | None]:
        """Ask to join a public meeting.

        Returns:
            The own state and a new token for the cookie, or None when the device
            keeps its token.

        Raises:
            NotFoundError: The code is unknown, or the meeting is closed or not
                public (``join_code_unknown``).
            ConflictError: The device is already admitted (``already_admitted``).
            RateLimitedError: A rejected or removed device asks again within 3 minutes
                (``retry_later``).
        """
        # The lock serializes the number of the pseudonym per meeting.
        meeting = await self.meeting_by_code(code, for_update=True)
        events = GuestEvents()
        other_events = GuestEvents()
        other_meeting: UUID | None = None
        existing = await self._by_token(token, for_update=True)
        new_token_value: str | None = None
        guest: MeetingGuest
        if (
            existing is not None
            and existing.meeting_id == meeting.id
            and existing.status
            in (
                "pending",
                "admitted",
                "rejected",
            )
        ):
            if existing.status == "admitted":
                raise ConflictError("You are already admitted.", code="already_admitted")
            self._check_retry(existing, now)
            guest = existing
            was_pending = guest.status == "pending"
            guest.display_name = name
            guest.requested_at = now
            guest.status = "pending"
            guest.decided_at = None
            guest.decided_by = None
            await self.session.flush()
            out = self._out(guest)
            if was_pending:
                events.updated.append((out, None))
            else:
                events.requested.append(out)
        else:
            if existing is not None:
                if existing.meeting_id == meeting.id:
                    self._check_retry(existing, now)
                elif existing.status in ("pending", "admitted"):
                    # The device leaves the other meeting: one device, one token. Its
                    # request or its seat ends, and its name goes at once, as on
                    # "Sitzung verlassen". The other meeting learns about it, so its
                    # lead list and the socket of the device follow.
                    existing.status = "left"
                    existing.decided_at = now
                    existing.display_name = None
                    other_meeting = existing.meeting_id
                    other_events.updated.append((self._out(existing), None))
                # One device, one token: the old row lets go of it.
                existing.token_hash = None
            new_token_value = new_token()
            seq = (
                await self.session.scalar(
                    select(func.coalesce(func.max(MeetingGuest.seq), 0)).where(
                        MeetingGuest.meeting_id == meeting.id
                    )
                )
            ) or 0
            guest = MeetingGuest(
                meeting_id=meeting.id,
                seq=seq + 1,
                display_name=name,
                status="pending",
                token_hash=token_hash(new_token_value),
                requested_at=now,
                last_seen_at=now,
            )
            self.session.add(guest)
            await self.session.flush()
            events.requested.append(self._out(guest))
        me = await self._me(meeting, guest, now)
        await self.session.commit()
        await self.publish(meeting.id, events)
        if other_meeting is not None:
            await self.publish(other_meeting, other_events)
        return me, new_token_value

    def _check_retry(self, guest: MeetingGuest, now: datetime) -> None:
        wait = self._retry_after(guest, now)
        if wait:
            raise RateLimitedError(
                "You can ask again in a few minutes.", retry_after=wait, code="retry_later"
            )

    async def resolve(
        self, code: str, token: str | None, *, for_update: bool = False
    ) -> tuple[Meeting, MeetingGuest]:
        """Find the guest of a device token and the meeting.

        The path code must be the current code of the meeting, except for an admitted
        guest: a rotation of the code keeps the admitted guests in.

        Raises:
            UnauthorizedError: No token (``guest_token_missing``).
            NotFoundError: Unknown token, a guest of another meeting, or a stale code
                (``guest_not_found``), or the meeting is not public
                (``meeting_not_public``).
        """
        if not token:
            raise UnauthorizedError("No guest token.", code="guest_token_missing")
        guest = await self._by_token(token, for_update=for_update)
        if guest is None:
            raise NotFoundError("Unknown guest.", code="guest_not_found")
        meeting = await self._meeting(guest.meeting_id)
        if meeting.join_code != normalize_code(code) and guest.status != "admitted":
            raise NotFoundError("Unknown guest.", code="guest_not_found")
        if not meeting.public_join:
            raise NotFoundError("The meeting is not public.", code="meeting_not_public")
        return meeting, guest

    async def me(self, code: str, token: str | None, *, now: datetime) -> GuestMe:
        """Return the own state, and the participant view once admitted."""
        meeting, guest = await self.resolve(code, token)
        if guest.last_seen_at is None or now - guest.last_seen_at >= _SEEN_INTERVAL:
            guest.last_seen_at = now
            await self.session.flush()
            await self.session.commit()
        return await self._me(meeting, guest, now)

    async def rename_self(
        self, code: str, token: str | None, name: str, *, now: datetime
    ) -> GuestMe:
        """Change the own name while the request waits."""
        meeting, guest = await self.resolve(code, token, for_update=True)
        if guest.status != "pending":
            raise ConflictError(
                "Only a waiting request can change its name.", code="guest_not_pending"
            )
        guest.display_name = name
        await self.session.flush()
        me = await self._me(meeting, guest, now)
        await self.session.commit()
        await self.publish(meeting.id, GuestEvents(updated=[(self._out(guest), None)]))
        return me

    async def leave(self, code: str, token: str | None, *, now: datetime) -> None:
        """Withdraw the request or leave the meeting.

        The own name becomes the pseudonym at once (decision 2026-10-06), and the token
        stops working. The ballots that the guest cast stay counted.
        """
        meeting, guest = await self.resolve(code, token, for_update=True)
        if guest.status in ("pending", "admitted"):
            guest.status = "left"
            guest.decided_at = now
        guest.display_name = None
        guest.token_hash = None
        await self.session.flush()
        out = (await self._outs([guest]))[0]
        await self.session.commit()
        await self.publish(meeting.id, GuestEvents(updated=[(out, None)]))

    async def cast(
        self,
        code: str,
        token: str | None,
        vote_id: UUID,
        choice: str,
        *,
        voting: VotingService,
        now: datetime,
    ) -> BallotAccepted:
        """Cast the ballot of an admitted guest.

        Raises:
            ForbiddenError: The guest is not admitted (``guest_not_admitted``), or the
                guests only watch (``guests_watch_only``), or the vote is for members
                only (``vote_members_only``).
            NotFoundError: The vote is not a vote of a public item of this meeting.
        """
        # The row lock reads the state of the guest again at the cast and serializes it
        # with a removal by the lead, like the account check of the member channel.
        meeting, guest = await self.resolve(code, token, for_update=True)
        if guest.status != "admitted":
            raise ForbiddenError("Only an admitted guest votes.", code="guest_not_admitted")
        if meeting.guests_mode != "vote":
            raise ForbiddenError("The guests only watch this meeting.", code="guests_watch_only")
        vote = await self.session.get(Vote, vote_id)
        if (
            vote is None
            or vote.meeting_id != meeting.id
            or not await self._public_item(vote.agenda_item_id)
        ):
            raise NotFoundError(f"vote {vote_id} not found")
        accepted = await voting.cast_guest(vote_id, guest.id, choice, now=now)
        if self.publisher is not None:
            try:
                await self.publisher.vote_tally(await voting.get(vote_id))
            except Exception:  # noqa: BLE001 - the broadcast is best effort
                logger.warning("vote_tally broadcast failed (vote=%s)", vote_id)
        return accepted

    async def _public_item(self, item_id: UUID | None) -> bool:
        if item_id is None:
            return False
        non_public = await self.session.scalar(
            select(MeetingAgendaItem.non_public).where(MeetingAgendaItem.id == item_id)
        )
        return non_public is False

    async def vote_is_public(self, vote_id: UUID, meeting_id: UUID) -> bool:
        """Tell if a vote belongs to a public agenda item of the meeting (guest filter)."""
        item_id = await self.session.scalar(
            select(Vote.agenda_item_id).where(Vote.id == vote_id, Vote.meeting_id == meeting_id)
        )
        return await self._public_item(item_id)

    # -- the guest view ----------------------------------------------------------------

    async def _me(self, meeting: Meeting, guest: MeetingGuest, now: datetime) -> GuestMe:
        view = await self._view(meeting, guest) if guest.status == "admitted" else None
        return GuestMe(
            guestId=guest.id,
            number=guest.seq,
            displayName=guest.display_name,
            status=guest.status,  # type: ignore[arg-type]
            retryAfter=self._retry_after(guest, now),
            meeting=await self._head(meeting),
            view=view,
        )

    async def _view(self, meeting: Meeting, guest: MeetingGuest) -> GuestView:
        items = (
            (
                await self.session.execute(
                    select(MeetingAgendaItem)
                    .where(MeetingAgendaItem.meeting_id == meeting.id)
                    .order_by(*agenda_order())
                )
            )
            .scalars()
            .all()
        )
        app_ids = [i.application_id for i in items if i.application_id is not None]
        titles: dict[UUID, str | None] = {}
        if app_ids:
            titles = {
                app_id: title_of(data)
                for app_id, data in (
                    await self.session.execute(
                        select(Application.id, Application.data).where(Application.id.in_(app_ids))
                    )
                ).all()
            }
        agenda = [
            GuestAgendaItem(
                id=item.id,
                position=position,
                title=titles.get(item.application_id) if item.application_id else item.title,
                kind="application" if item.application_id else "freetext",
                nonPublic=item.non_public,
                # Never the text of a non-public item.
                body=None if item.non_public else item.body,
            )
            for position, item in enumerate(items, start=1)
        ]
        public_ids = [item.id for item in items if not item.non_public]
        present_members = (
            await self.session.scalar(
                select(func.count())
                .select_from(MeetingAttendance)
                .where(
                    MeetingAttendance.meeting_id == meeting.id,
                    MeetingAttendance.status == "present",
                )
            )
        ) or 0
        admitted, _ = await self.counts(meeting.id)
        votes = await self._votes(meeting, guest, public_ids)
        return GuestView(
            currentAgendaItemId=meeting.current_agenda_item_id,
            presentMembers=present_members,
            admittedGuests=admitted,
            agenda=agenda,
            votes=votes,
        )

    async def _votes(
        self, meeting: Meeting, guest: MeetingGuest, public_ids: list[UUID]
    ) -> list[GuestVote]:
        if not public_ids:
            return []
        rows = (
            (
                await self.session.execute(
                    select(Vote)
                    .where(
                        Vote.meeting_id == meeting.id,
                        Vote.agenda_item_id.in_(public_ids),
                        Vote.status.in_(("open", "closed")),
                    )
                    .order_by(Vote.created_at)
                )
            )
            .scalars()
            .all()
        )
        voting = VotingService(self.session)
        voter = guest_voter_sub(guest.id)
        out: list[GuestVote] = []
        for vote in rows:
            config = VoteConfig.from_stored(vote.config)
            view = await voting.get(vote.id)
            mine = await voting.my_ballot(vote, voter, secret=config.secret)
            can_cast = (
                vote.status == "open"
                and config.guests_vote
                and meeting.guests_mode == "vote"
                and not mine.cast
            )
            out.append(
                GuestVote(
                    id=vote.id,
                    agendaItemId=vote.agenda_item_id,
                    question=vote.question,
                    options=list(config.options),
                    status=vote.status,  # type: ignore[arg-type]
                    secret=config.secret,
                    majorityRule=config.majority_rule,
                    guestsVote=config.guests_vote,
                    quorum=config.quorum,
                    openedAt=vote.opens_at,
                    closedAt=vote.closed_at,
                    result=vote.result,  # type: ignore[arg-type]
                    failedReason=view.tally.failed_reason,
                    tally=GuestTally(
                        counts=view.tally.counts,
                        voted=view.tally.voted,
                        present=view.tally.present,
                        revealed=view.tally.revealed,
                        leading=view.tally.leading,
                        presentMembers=view.tally.present_members,
                        presentGuests=view.tally.present_guests,
                    ),
                    myBallot=mine,
                    canCast=can_cast,
                )
            )
        return out
