"""The draft of a protocol: create, edit, delete, embed votes, approval, withheld, reopen."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.files.cd_resolver import cd_variant_key_for_gremium
from app.modules.gremien.models import Gremium
from app.modules.meetings.models import Meeting
from app.modules.meetings.protocol_models import Protocol, ProtocolVoteRef
from app.modules.protocol import approval
from app.modules.protocol.schemas import ProtocolOut
from app.modules.protocol.service.base import ProtocolServiceBase
from app.modules.protocol.service.snippets import _snippet, _vote_title
from app.modules.voting.service import VotingService
from app.shared.errors import ConflictError, NotFoundError


class DraftOps(ProtocolServiceBase):
    """Draft writes and status changes outside the finalization."""

    async def get_or_create(self, meeting_id: UUID, *, author: str | None = None) -> ProtocolOut:
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

        A draft that was final once (spec 000983) went out by mail, so it stays a
        record and answers 409 too.

        Raises:
            NotFoundError: No protocol has this id (404).
            ConflictError: The protocol is final, under render, or was final once (409).
        """
        protocol = await self._get(protocol_id)
        self._ensure_draft(protocol)
        if getattr(protocol, "sent_at", None) is not None:
            raise ConflictError(
                "The protocol went out once and is a record. It cannot be deleted.",
                code="protocol_finalized",
            )
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

    async def embed_votes(self, protocol_id: UUID, vote_ids: Sequence[UUID]) -> ProtocolOut:
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

    async def set_approval(
        self, protocol_id: UUID, meeting_id: UUID | None, *, now: datetime, actor: str
    ) -> ProtocolOut:
        """Set or remove the approval mark of a protocol (spec 000924).

        ``meeting_id`` is the meeting that approved the protocol; None removes the mark.
        The caller commits.

        Raises:
            ConflictError: The protocol is not final (409 ``protocol_not_final``).
            ValidationProblem: The meeting is not another meeting of the same Gremium
                (422 ``invalid_approval_meeting``).
        """
        protocol = await self._get(protocol_id, for_update=True)
        if meeting_id is None:
            await approval.unapprove(self.session, protocol, actor=actor)
        else:
            await approval.approve(self.session, protocol, meeting_id, now=now, actor=actor)
        return await self._to_out(protocol)

    async def reopen(self, protocol_id: UUID, *, actor: str) -> ProtocolOut:
        """Set a final protocol back to draft (spec 000983). The caller commits.

        The protocol leaves the public pages, because they show a final protocol only.
        The next finalization renders and sends again.

        Raises:
            ConflictError: The protocol is not final (409 ``protocol_not_final``), or it
                has an approval mark (409 ``protocol_approved``).
        """
        protocol = await self._get(protocol_id, for_update=True)
        await approval.reopen(self.session, protocol, actor=actor)
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
