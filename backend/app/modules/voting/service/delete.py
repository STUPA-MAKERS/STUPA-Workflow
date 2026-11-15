"""The delete of a vote: one vote, the votes of an agenda item, a meeting or a Gremium."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import and_, delete, func, or_, select, update

from app.modules.applications.models import StatusEvent
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.meetings.protocol_models import ProtocolVoteRef
from app.modules.voting import election as election_mod
from app.modules.voting.models import SecretBallot, Vote, VotedMarker
from app.modules.voting.service.base import (
    VotingServiceBase,
    _refuse_open,
)
from app.shared.errors import ConflictError, ForbiddenError, NotFoundError


class VoteDeleteOps(VotingServiceBase):
    """The delete of a vote: one vote, the votes of an agenda item, a meeting or a Gremium."""

    async def delete(self, vote_id: UUID, *, meeting_id: UUID, actor: str) -> None:
        """Delete a meeting-bound vote and write a ``vote_delete`` audit entry.

        The ballots cascade through the foreign key. The method deletes only a vote of
        this meeting, and only a ``draft`` or ``cancelled`` vote. An open or closed
        vote is part of the record of the meeting, and a closed result may already
        have fired a flow branch. The same rule keeps an agenda item with such a vote,
        so two deletes cannot get around it. The caller cancels an open vote
        first. The caller (router) checks the authorization and the meeting status:
        only a ``planned`` or ``live`` meeting deletes a vote.

        Raises:
            NotFoundError: The vote does not belong to this meeting.
            ConflictError: The vote is open or closed (``vote_not_deletable``).
        """
        vote = await self._get_vote(vote_id, for_update=True)
        if vote.meeting_id != meeting_id:
            raise NotFoundError(f"vote {vote_id} not found in this meeting")
        if vote.status in ("open", "closed"):
            raise ConflictError(
                "An open or closed vote is part of the record of the meeting and "
                "cannot be deleted. Cancel an open vote instead.",
                code="vote_not_deletable",
            )
        await self._delete_audited(vote, actor=actor)
        await self.session.commit()

    async def delete_for_agenda_item(
        self, agenda_item_id: UUID, *, actor: str, may_delete: bool
    ) -> list[UUID]:
        """Delete the draft and cancelled votes of an agenda item, without a commit.

        The agenda-item remove calls this first. The foreign key
        ``vote.agenda_item_id`` no longer cascades, so the remove deletes these votes
        itself, each with a ``vote_delete`` audit entry. An open or closed vote is part
        of the record of the meeting and blocks the remove.

        ``may_delete`` tells if the caller may delete a vote of the meeting. The
        agenda right alone (``protocol.write``) does not delete a vote: that needs
        ``canManageVotes``, as on ``DELETE /meetings/{id}/votes/{voteId}``.

        Returns:
            The ids of the deleted votes.

        Raises:
            ConflictError: The agenda item has an open or closed vote
                (``agenda_item_has_vote``). The method then deletes nothing.
            ForbiddenError: The agenda item has a draft or cancelled vote and
                ``may_delete`` is false. The method then deletes nothing.
        """
        rows = (
            (
                await self.session.execute(
                    select(Vote)
                    .where(Vote.agenda_item_id == agenda_item_id)
                    .order_by(Vote.created_at)
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        if any(vote.status in ("open", "closed") for vote in rows):
            raise ConflictError(
                "This agenda item has an open or closed vote and cannot be removed.",
                code="agenda_item_has_vote",
            )
        if rows and not may_delete:
            raise ForbiddenError(
                "This agenda item has votes. Only a person who manages the votes of "
                "the meeting can remove it."
            )
        for vote in rows:
            await self._delete_audited(vote, actor=actor)
        return [vote.id for vote in rows]

    async def delete_for_meeting(self, meeting_id: UUID, *, actor: str) -> list[UUID]:
        """Delete every vote of a meeting, in any status, without a commit.

        The meeting delete calls this under the lock of the meeting row, in its own
        transaction. The method locks the vote rows (meeting row first, vote rows
        after it). It then deletes, in this order, the protocol references, the secret
        ballots and the voted markers of these votes, clears the vote
        reference of the status events, and deletes each vote with a ``vote_delete``
        audit entry (reason ``meeting_deleted``). The foreign keys would cascade or
        set NULL too, but the explicit deletes keep the order and the audit visible.

        An application that such a vote decided keeps its status. Its status event
        keeps the note ``vote:<result>``, and the timeline shows the vote as deleted.

        The audit entries hold id references and the status only, never a voter and
        never a choice, so the delete of a secret vote reveals nothing.

        Returns:
            The ids of the deleted votes, in creation order.

        Raises:
            ConflictError: A vote of the meeting is open (``open_vote``). The method
                then deletes nothing.
        """
        rows = (
            (
                await self.session.execute(
                    select(Vote)
                    .where(Vote.meeting_id == meeting_id)
                    .order_by(Vote.created_at)
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        _refuse_open(rows, owner="meeting")
        return await self.delete_locked_votes(rows, actor=actor, reason="meeting_deleted")

    async def lock_for_gremium_delete(
        self, gremium_id: UUID, meeting_ids: Sequence[UUID]
    ) -> list[Vote]:
        """Lock every vote that a Gremium delete checks, without a commit.

        These are the votes of the meetings of the Gremium (``meeting_ids``) and the
        votes that hold the Gremium id in ``eligible_group`` and have no meeting, for
        example the vote of an application outside a meeting. The delete takes only
        the meeting votes along; a vote without a meeting stays, but an open one
        refuses the delete. One statement locks
        them all in id order, BEFORE the delete writes its first audit entry. The
        audit write takes the advisory lock of the audit chain, and a vote cancel or
        close locks its vote first and audits after it. A vote lock after the first
        audit entry could therefore close a deadlock cycle.

        Returns:
            The locked votes, in id order.

        Raises:
            ConflictError: One of the votes is open (``open_vote``).
        """
        rows = (
            (
                await self.session.execute(
                    select(Vote)
                    .where(
                        or_(
                            Vote.meeting_id.in_(list(meeting_ids)),
                            and_(
                                Vote.eligible_group == str(gremium_id),
                                Vote.meeting_id.is_(None),
                            ),
                        )
                    )
                    .order_by(Vote.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        )
        _refuse_open(rows, owner="Gremium")
        return list(rows)

    async def delete_locked_votes(
        self, rows: Sequence[Vote], *, actor: str, reason: str
    ) -> list[UUID]:
        """Delete votes that the caller locked, with their rows, without a commit.

        The method deletes, in this order, the protocol references, the secret
        ballots and the voted markers of these votes, clears the vote
        reference of the status events, and deletes each vote with a ``vote_delete``
        audit entry with ``reason`` (``meeting_deleted``).

        Returns:
            The ids of the deleted votes, in the order of ``rows``.
        """
        ids = [vote.id for vote in rows]
        if ids:
            for model in (ProtocolVoteRef, SecretBallot, VotedMarker):
                await self.session.execute(delete(model).where(model.vote_id.in_(ids)))
            await self.session.execute(
                update(StatusEvent).where(StatusEvent.vote_id.in_(ids)).values(vote_id=None)
            )
        for vote in rows:
            await self._delete_audited(vote, actor=actor, reason=reason)
        return ids

    async def _delete_audited(self, vote: Vote, *, actor: str, reason: str | None = None) -> None:
        """Write ``vote_delete`` for a loaded vote and delete it, without a commit.

        ``reason`` names a delete that another delete caused (``meeting_deleted``).

        A deleted runoff releases its link, so it no longer blocks a new runoff of its
        election.
        """
        data: dict[str, str | None] = {
            **self._audit_refs(vote),
            "agendaItemId": str(vote.agenda_item_id) if vote.agenda_item_id else None,
            "status": vote.status,
            **({"reason": reason} if reason is not None else {}),
        }
        await election_mod.release_runoff_link(self.session, vote)
        await audit_record(
            self.session,
            actor=actor,
            action=AuditAction.VOTE_DELETE,
            target_type="vote",
            target_id=str(vote.id),
            data=data,
        )
        await self.session.delete(vote)
        await self.session.flush()

    async def _ballot_count(self, vote_id: UUID) -> int:
        """Count every recorded participation of a vote.

        The ``voted_marker`` rows count too. A vote splits the identity from the
        choice, so the marker is the only trace that somebody voted.
        """
        counts = [
            await self.session.scalar(
                select(func.count()).select_from(model).where(model.vote_id == vote_id)
            )
            for model in (SecretBallot, VotedMarker)
        ]
        return sum(n or 0 for n in counts)

    async def delete_standalone(self, vote_id: UUID, *, actor: str) -> None:
        """Delete a standalone application-bound vote that is a draft or cancelled.

        The rule is the same as for a meeting vote (§F/meetings/voting/000029): a
        ``draft`` or ``cancelled`` vote can be deleted, its ballots go with it (FK
        cascade). An ``open`` or ``closed`` vote is part of the record of the Gremium,
        and its result may already have fired a flow branch, so it gives 409
        ``vote_not_deletable``. A vote that belongs to a meeting is not reachable here.
        That one has its own route, ``DELETE /meetings/{id}/votes/{id}``, with the
        meeting-scoped ``canManageVotes`` check. Duplicating it here would give a
        second, weaker path to the same row.

        The caller (router) runs the gremium-scoped manage check
        (``assert_can_manage_vote``), like open, close and cancel.

        Raises:
            NotFoundError: No vote has this id (404).
            ConflictError: The vote belongs to a meeting (``vote_meeting_bound``), or
                it is open or closed (``vote_not_deletable``) (409).
        """
        vote = await self._get_vote(vote_id)
        if vote.meeting_id is not None:
            raise ConflictError(
                "This vote belongs to a meeting; delete it through the meeting.",
                code="vote_meeting_bound",
            )
        if vote.status in ("open", "closed"):
            raise ConflictError(
                "An open or closed vote is part of the record and cannot be deleted. "
                "Cancel an open vote instead.",
                code="vote_not_deletable",
            )
        await self._delete_audited(vote, actor=actor)
        await self.session.commit()
