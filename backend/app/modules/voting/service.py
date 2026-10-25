"""Voting service: create -> open -> cast -> close (or cancel).

Race safety: the DB enforces one ballot per voter. A ballot never changes after the
cast.

* open (``secret=false``): ``INSERT ... ON CONFLICT (vote_id, voter_sub) DO NOTHING``.
  An empty ``RETURNING`` means a second cast -> 409 ``already_voted``.
* secret (``secret=true``): ``voted_marker`` (UNIQUE) records 'has voted'. The ballot
  lands without an identity in ``secret_ballot``. A second cast gives 409
  ``already_voted`` too.

Close and cancel set ``closed_at``. Open, close and cancel write an audit entry.
A close always ends the vote: when the pass or fail transition of the
application cannot fire, the close still commits, writes ``vote_branch_blocked`` and
returns ``branchFired=false``.

RBAC is fail-closed and gremium-scoped. ``vote.eligible_group`` holds the UUID of the
gremium that votes. A ``cast`` needs the gremium permission ``vote.cast`` there: only an
active gremium role with ``vote.cast`` writes the namespaced group key
``vote:<gremium_id>``. No global permission grants a vote right. The quorum denominator
(``MeetingService.vote_eligible_count``) reads the same roster, and ``create`` stores it
as ``eligible_count``, so the counted set and the admitted set stay equal. A vote with a
free group key (an old row) admits nobody: the call gets 403.

The livevote imports are local, because the livevote modules import this module.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.applications.decision import (
    DecisionIn,
    check_approved_amount,
    not_allowed_problem,
    record_decision,
)
from app.modules.applications.models import Application, ApplicationDecision, StatusEvent
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.auth.principal import Principal
from app.modules.auth.rbac import vote_group_key
from app.modules.delegations.service import voting_delegation_check
from app.modules.flow.dispatch import ActionDispatcher, NullActionDispatcher
from app.modules.flow.service import FlowService, StagedFire
from app.modules.protocol.models import ProtocolVoteRef
from app.modules.voting import election as election_mod
from app.modules.voting import poll as poll_mod
from app.modules.voting import tally as tally_mod
from app.modules.voting.models import Ballot, SecretBallot, Vote, VotedMarker
from app.modules.voting.schemas import (
    BallotAccepted,
    MyBallot,
    PollResultOut,
    TallyOut,
    VoteClosed,
    VoteCreate,
    VoteCreateInternal,
    VoteKind,
    VoteListItem,
    VoteOut,
    VoteStatus,
)
from app.shared.config_schemas import ElectionConfig, PollConfig, VoteConfig
from app.shared.errors import ConflictError, ForbiddenError, NotFoundError, ValidationProblem
from app.shared.paging import DEFAULT_LIMIT, Page

#: The problem code of a second cast (REST 409 and the live-vote error frame).
ALREADY_VOTED = "already_voted"

#: 409 code and audit reason: the Gremium of a vote does not decide the current vote
#: state of its application (`application.vote_gremium_id`).
VOTE_GREMIUM_MISMATCH = "vote_gremium_mismatch"


def vote_gremium_mismatch_error() -> ConflictError:
    """Build the 409 for a vote of a Gremium that does not decide the application."""
    return ConflictError(
        "The Gremium of this vote does not decide the current vote of the application.",
        code=VOTE_GREMIUM_MISMATCH,
    )


#: The ballot of any vote kind: an option, a list of ids, or the answers of a date poll.
Choice = str | list[str] | Mapping[str, str]

#: The voter key of a guest of a public meeting: ``guest:<meeting_guest.id>``. A
#: guest is not a principal, so the key never collides with an OIDC ``sub``.
GUEST_VOTER_PREFIX = "guest:"


def guest_voter_sub(guest_id: UUID) -> str:
    """Return the ``voter_sub`` of a guest ballot."""
    return f"{GUEST_VOTER_PREFIX}{guest_id}"


def open_tally_revealed(present: int, voted: int, expected: int) -> bool:
    """Return True when an open, non-secret vote can show its running tally.

    The running count becomes visible only after all expected ballots are in.
    Otherwise the interim tally leaks on the beamer and to the voters. ``expected`` is
    the denominator. It holds the present members plus the active vote delegations
    whose delegator is ABSENT. The delegate casts a represented ballot, and ``voted``
    counts that ballot. Without that add-on ``voted`` could exceed ``present`` before
    all present members voted, and reveal the tally too early. The live-vote reload
    path uses this rule too.
    """
    return present > 0 and voted >= expected



async def holds_gremium_vote_role(
    session: AsyncSession, gremium_id: UUID, principal: Principal
) -> bool:
    """Tell whether a gremium role gives ``vote.manage`` or ``session.manage`` here.

    Both go through ``policy.holds_gremium_permission``, so the OAuth scope cap
    applies. The read rule of a vote without a meeting
    (``VotingService.assert_can_read``) uses this part alone, because that rule
    checks the admin role before, with a read right instead of ``vote.manage``.
    """
    from app.modules.auth.policy import holds_gremium_permission

    for perm in ("vote.manage", "session.manage"):
        if await holds_gremium_permission(session, principal, perm, gremium_id):
            return True
    return False


async def manages_votes_in_gremium(
    session: AsyncSession, gremium_id: UUID, principal: Principal
) -> bool:
    """Tell whether the principal manages the votes of this gremium.

    This is the single source of the gremium rule of vote management: the admin role
    (``admin_bypass`` with ``vote.manage``) or a gremium role with ``vote.manage`` or
    ``session.manage`` (``holds_gremium_vote_role``). The OAuth scope cap applies to
    every path, so an admin token with only the ``read`` scope cannot manage.
    ``VotingService.can_manage_group`` applies it to a vote without a meeting, and
    ``PermissionOps.can_manage_votes`` adds the session lead and the protokollant of
    a meeting to it. No global permission grants the right.
    """
    from app.modules.auth.policy import admin_bypass

    if admin_bypass(principal, "vote.manage"):
        return True
    return await holds_gremium_vote_role(session, gremium_id, principal)


def _refuse_open(rows: Sequence[Vote], *, owner: str) -> None:
    """Refuse a delete while one of the votes is open.

    ``owner`` names the meeting or the Gremium in the conflict message.

    Raises:
        ConflictError: A vote is open (``open_vote``).
    """
    if any(vote.status == "open" for vote in rows):
        raise ConflictError(
            f"a vote of this {owner} is still open — close or cancel it first",
            code="open_vote",
        )


class VotingService:
    """Vote service on one ``AsyncSession`` with an optional flow dispatcher."""

    def __init__(self, session: AsyncSession, dispatcher: ActionDispatcher | None = None) -> None:
        """Bind the service to a session and an optional flow dispatcher."""
        self.session = session
        self.dispatcher: ActionDispatcher = dispatcher or NullActionDispatcher()

    async def _get_vote(self, vote_id: UUID, *, for_update: bool = False) -> Vote:
        """Load a vote by id.

        ``for_update`` locks the row and serializes cast against close. Without the
        lock a last-second ballot could commit between the tally and ``status=closed``,
        and then be missing from the recorded result.

        A locked read sets ``populate_existing``, because it must see the committed
        values and not a stale identity-map copy from an earlier unlocked read in this
        transaction.

        Raises:
            NotFoundError: No vote has this id.
        """
        stmt = select(Vote).where(Vote.id == vote_id)
        if for_update:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        vote = (await self.session.execute(stmt)).scalar_one_or_none()
        if vote is None:
            raise NotFoundError(f"vote {vote_id} not found")
        return vote

    async def _lock_live_meeting(
        self,
        meeting_id: UUID,
        *,
        agenda_item_id: UUID | None = None,
        planned_ok: bool = False,
    ) -> None:
        """Lock the meeting row and require a ``live`` meeting.

        ``planned_ok`` also accepts a ``planned`` meeting. The create of a prepared
        draft vote uses it: a draft can wait in a planned meeting, but it opens only
        in a live one.

        The meeting close, the meeting delete and the agenda-item remove take the
        same lock. Thus a vote cannot open in a meeting that closes or is deleted at
        the same time, and it cannot bind to an agenda item that is removed at the
        same time. Take this lock BEFORE a vote
        row lock: the close locks the meeting first and the draft votes after it.

        Raises:
            NotFoundError: The meeting does not exist, or ``agenda_item_id`` is not
                an agenda item of the meeting.
            ConflictError: The meeting is not ``live`` (``meeting_not_started`` or
                ``meeting_closed``).
        """
        from app.modules.livevote.models import Meeting, MeetingAgendaItem

        status = await self.session.scalar(
            select(Meeting.status).where(Meeting.id == meeting_id).with_for_update()
        )
        if status is None:
            raise NotFoundError(f"meeting {meeting_id} not found")
        if status == "planned" and not planned_ok:
            raise ConflictError(
                "The meeting has not started. Start it before opening a vote.",
                code="meeting_not_started",
            )
        if status == "closed":
            raise ConflictError(
                "The meeting is closed. A vote can no longer open.",
                code="meeting_closed",
            )
        if agenda_item_id is not None:
            found = await self.session.scalar(
                select(MeetingAgendaItem.id).where(
                    MeetingAgendaItem.id == agenda_item_id,
                    MeetingAgendaItem.meeting_id == meeting_id,
                )
            )
            if found is None:
                raise NotFoundError(f"agenda item {agenda_item_id} not found")

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
        ballots, the voted markers and the ballots of these votes, clears the vote
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
        ballots, the voted markers and the ballots of these votes, clears the vote
        reference of the status events, and deletes each vote with a ``vote_delete``
        audit entry with ``reason`` (``meeting_deleted``).

        Returns:
            The ids of the deleted votes, in the order of ``rows``.
        """
        ids = [vote.id for vote in rows]
        if ids:
            for model in (ProtocolVoteRef, SecretBallot, VotedMarker, Ballot):
                await self.session.execute(delete(model).where(model.vote_id.in_(ids)))
            await self.session.execute(
                update(StatusEvent).where(StatusEvent.vote_id.in_(ids)).values(vote_id=None)
            )
        for vote in rows:
            await self._delete_audited(vote, actor=actor, reason=reason)
        return ids

    async def _delete_audited(
        self, vote: Vote, *, actor: str, reason: str | None = None
    ) -> None:
        """Write ``vote_delete`` for a loaded vote and delete it, without a commit.

        ``reason`` names a delete that another delete caused (``meeting_deleted``).

        A deleted runoff releases its link, so it no longer blocks a new runoff of its
        election.
        """
        data: dict[str, str | None] = {
            **self._audit_refs(vote),
            "agendaItemId": str(vote.agenda_item_id) if vote.agenda_item_id else None,
            "status": vote.status,
        }
        if reason is not None:
            data["reason"] = reason
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
        """Count every recorded participation of a vote, open and secret.

        The ``voted_marker`` rows count too. A secret vote splits the identity
        from the choice, so the marker is the only trace that somebody voted.
        """
        total = 0
        for model in (Ballot, SecretBallot, VotedMarker):
            total += (
                await self.session.scalar(
                    select(func.count()).select_from(model).where(model.vote_id == vote_id)
                )
            ) or 0
        return total

    async def delete_standalone(self, vote_id: UUID, *, actor: str) -> None:
        """Delete a standalone application-bound vote that never ran.

        The vote must still be ``draft`` and must hold no ballot. Anything
        further along stays with ``cancel``: an opened vote is part of the
        record of the Gremium, and its result may already have fired a flow
        branch. A vote that belongs to a meeting is not reachable here. That
        one has its own route, ``DELETE /meetings/{id}/votes/{id}``, with the
        meeting-scoped ``canManageVotes`` check. Duplicating it here would give
        a second, weaker path to the same row.

        The caller (router) runs the gremium-scoped manage check
        (``assert_can_manage_vote``), like open, close and cancel.

        Raises:
            NotFoundError: No vote has this id (404).
            ConflictError: The vote belongs to a meeting, is no longer a draft,
                or already holds ballots (409).
        """
        vote = await self._get_vote(vote_id)
        if vote.meeting_id is not None:
            raise ConflictError(
                "This vote belongs to a meeting; delete it through the meeting.",
                code="vote_meeting_bound",
            )
        if vote.status != "draft":
            raise ConflictError(
                "Only a vote that never opened can be deleted; cancel it instead.",
                code="vote_not_draft",
            )
        if await self._ballot_count(vote_id) > 0:
            raise ConflictError(
                "This vote already holds ballots and cannot be deleted.",
                code="vote_has_ballots",
            )
        await self._delete_audited(vote, actor=actor)
        await self.session.commit()

    async def _get_application(
        self, application_id: UUID, *, confirmed_only: bool = False
    ) -> Application:
        """Load the application, or raise 404.

        `confirmed_only=True` also gives 404 for an unconfirmed guest application
        (`email_confirmed_at IS NULL`). Such an application rests in the flow and stays
        invisible, as on the flow routes.
        """
        stmt = select(Application).where(Application.id == application_id)
        if confirmed_only:
            stmt = stmt.where(Application.email_confirmed_at.is_not(None))
        app = (await self.session.execute(stmt)).scalar_one_or_none()
        if app is None:
            raise NotFoundError(f"application {application_id} not found")
        return app

    @staticmethod
    def _config(vote: Vote) -> VoteConfig:
        return VoteConfig.from_stored(vote.config)

    @staticmethod
    def _audit_refs(vote: Vote) -> dict[str, str | None]:
        """Return the id references of a vote for its audit entries (no voter)."""
        return {
            "applicationId": str(vote.application_id) if vote.application_id else None,
            "meetingId": str(vote.meeting_id) if vote.meeting_id else None,
            "eligibleGroup": vote.eligible_group,
        }

    async def _aggregate(self, vote: Vote, config: VoteConfig) -> dict[str, int]:
        """Count the votes per option: open from ``ballot``, secret from ``secret_ballot``."""
        return tally_mod.tally(config.options, await self._choices(vote, config))

    async def _present_count(self, vote: Vote) -> int:
        """Count the present meeting members (reveal denominator), or 0 without a meeting."""
        if vote.meeting_id is None:
            return 0
        from app.modules.livevote.models import MeetingAttendance

        return (
            await self.session.scalar(
                select(func.count())
                .select_from(MeetingAttendance)
                .where(
                    MeetingAttendance.meeting_id == vote.meeting_id,
                    MeetingAttendance.status == "present",
                )
            )
        ) or 0

    async def _admitted_guest_count(self, vote: Vote) -> int:
        """Count the admitted guests of the meeting of the vote, or 0 without one."""
        if vote.meeting_id is None:
            return 0
        from app.modules.livevote.models import MeetingGuest

        return (
            await self.session.scalar(
                select(func.count())
                .select_from(MeetingGuest)
                .where(
                    MeetingGuest.meeting_id == vote.meeting_id,
                    MeetingGuest.status == "admitted",
                )
            )
        ) or 0

    async def _guest_attendance(self, vote: Vote, config: VoteConfig) -> int:
        """Count the guests of a vote.

        A members vote counts the admitted guests (display only). A vote with guests
        counts the admitted guests plus the guests who left or were removed after
        their ballot: the ballot stays counted, so the guest stays part of the base.
        Without this the turnout could reach the expected ballots before every
        present person voted and reveal the running tally too early, and the number
        fixed at the close could be smaller than the cast ballots.
        """
        if not config.guests_vote:
            return await self._admitted_guest_count(vote)
        from app.modules.livevote.models import MeetingGuest

        admitted = {
            guest_voter_sub(gid)
            for gid in (
                await self.session.execute(
                    select(MeetingGuest.id).where(
                        MeetingGuest.meeting_id == vote.meeting_id,
                        MeetingGuest.status == "admitted",
                    )
                )
            )
            .scalars()
            .all()
        }
        voters: set[str] = set()
        for model in (Ballot, VotedMarker):
            voters.update(
                (
                    await self.session.execute(
                        select(model.voter_sub).where(
                            model.vote_id == vote.id,
                            model.voter_sub.startswith(GUEST_VOTER_PREFIX),
                        )
                    )
                )
                .scalars()
                .all()
            )
        return len(admitted | voters)

    async def _absent_delegated_count(self, vote: Vote) -> int:
        """Count the active vote delegations whose delegator is NOT present.

        The scope is this meeting and this gremium. The delegate casts a represented
        ballot, and ``voted`` counts it even though the delegator is absent. This
        add-on to the reveal denominator stops ``voted`` from exceeding ``present`` and
        revealing the tally too early. ``eligible_group`` holds the gremium UUID as
        text. The method returns 0 when that text is not a UUID, because then no
        delegation exists.
        """
        if vote.meeting_id is None:
            return 0
        try:
            gremium_id = UUID(vote.eligible_group)
        except (ValueError, TypeError):
            return 0
        from app.modules.delegations.models import MeetingDelegation
        from app.modules.livevote.models import MeetingAttendance

        present_subq = (
            select(MeetingAttendance.principal_id)
            .where(
                MeetingAttendance.meeting_id == vote.meeting_id,
                MeetingAttendance.status == "present",
            )
            .scalar_subquery()
        )
        return (
            await self.session.scalar(
                select(func.count())
                .select_from(MeetingDelegation)
                .where(
                    MeetingDelegation.meeting_id == vote.meeting_id,
                    MeetingDelegation.gremium_id == gremium_id,
                    MeetingDelegation.delegate_voting.is_(True),
                    MeetingDelegation.delegator_principal_id.notin_(present_subq),
                )
            )
        ) or 0

    async def _tally_out(
        self, vote: Vote, config: VoteConfig, counts: dict[str, int], eligible: int
    ) -> TallyOut:
        """Build the tally and the turnout progress.

        ``counts`` and ``leading`` are visible only when ``revealed``. That happens
        when the vote is closed, or when the vote is not secret and all present members
        have voted. An open non-secret vote without a meeting stays visible, because
        there is no notion of 'present'. When the tally is hidden, only ``voted`` and
        ``present`` travel.

        A vote with guests counts the admitted guests as present too: they are
        expected ballots. ``presentMembers`` and ``presentGuests`` give the attendance
        of a meeting vote, live while it runs and fixed after the close.

        An election counts ballots, not votes, and has no leader. A poll only counts: it
        has no quorum and no leader.

        The present denominator is queried only for an open vote with a meeting, because
        only there it changes the reveal decision. A secret vote without a meeting never
        reveals a running tally. The expected ballots of a meeting vote are the present
        members (and guests) plus the represented votes of absent delegators, because
        without them the interim count leaks too early.
        """
        voted = sum(counts.values())
        outcome = tally_mod.result(config, counts, eligible)
        quorum_met, lead = outcome.quorum_met, outcome.leading
        if election_mod.is_election(vote):
            ev = await self._election_outcome(vote, eligible)
            counts, voted, quorum_met, lead = ev.display_counts(), ev.ballots, ev.quorum_met, None
        elif poll_mod.is_poll(vote):
            pv = await self._poll_outcome(vote)
            counts, voted, quorum_met, lead = pv.display_counts(), pv.ballots, True, None
        members: int | None = None
        guests: int | None = None
        if vote.status == "closed":
            present, revealed = 0, True
            members = getattr(vote, "present_members", None)
            guests = getattr(vote, "present_guests", None)
        elif vote.meeting_id is None:
            present, revealed = 0, not config.secret
        else:
            members = await self._present_count(vote)
            guests = await self._guest_attendance(vote, config)
            present = members + guests if config.guests_vote else members
            if config.secret:
                revealed = False
            else:
                expected = present + await self._absent_delegated_count(vote)
                revealed = open_tally_revealed(present, voted, expected)
        return TallyOut(
            counts=counts if revealed else {},
            eligible=eligible,
            voted=voted,
            present=present,
            revealed=revealed,
            quorumMet=quorum_met,
            leading=lead if revealed else None,
            result=None,
            presentMembers=members,
            presentGuests=guests,
        )

    def _to_out(
        self,
        vote: Vote,
        config: VoteConfig,
        tally_out: TallyOut,
        poll_live: PollResultOut | None = None,
    ) -> VoteOut:
        return VoteOut(
            id=vote.id,
            applicationId=vote.application_id,
            meetingId=vote.meeting_id,
            agendaItemId=getattr(vote, "agenda_item_id", None),
            question=getattr(vote, "question", None),
            eligibleGroup=vote.eligible_group,
            config=config,
            status=vote.status,  # type: ignore[arg-type]
            opensAt=vote.opens_at,
            closesAt=vote.closes_at,
            result=vote.result,  # type: ignore[arg-type]
            secret=config.secret,
            majorityRule=config.majority_rule,
            quorum=config.quorum,
            openedAt=vote.opens_at,
            closedAt=vote.closed_at,
            tally=tally_out,
            guestsVote=config.guests_vote,
            proposal=DecisionIn.from_stored(getattr(vote, "proposal", None)),
            **election_mod.election_fields(vote),
            **poll_mod.poll_fields(vote, poll_live),
        )

    @staticmethod
    def _check_proposal(application: Application, proposal: DecisionIn | None) -> None:
        """Check the approved amount of a proposal against the requested amount.

        Raises:
            ValidationProblem: `approved_amount_invalid` or
                `approved_amount_exceeds_requested` (422).
        """
        if proposal is not None:
            check_approved_amount(application.amount, proposal.approved_amount)

    async def _choices(self, vote: Vote, config: VoteConfig) -> Sequence[str | None]:
        """Load the stored choices: open from ``ballot``, secret from ``secret_ballot``."""
        model = SecretBallot if config.secret else Ballot
        return (
            (await self.session.execute(select(model.choice).where(model.vote_id == vote.id)))
            .scalars()
            .all()
        )

    async def _election_outcome(self, vote: Vote, eligible: int) -> tally_mod.ElectionOutcome:
        """Tally an election from its stored ballots."""
        config = election_mod.election_config(vote)
        choices = await self._choices(vote, config.as_vote_config())
        return election_mod.outcome_of(config, choices, eligible, getattr(vote, "round", 1) or 1)

    async def _poll_outcome(self, vote: Vote) -> tally_mod.PollOutcome:
        """Tally a poll from its stored ballots."""
        config = poll_mod.poll_config(vote)
        choices = await self._choices(vote, config.as_vote_config())
        return tally_mod.tally_poll(choices, config)

    async def create(
        self, application_id: UUID, payload: VoteCreate, principal: Principal
    ) -> VoteOut:
        """Create a draft application vote from the API body.

        ``eligibleGroup`` must name an existing gremium. The vote must also belong to
        the gremium of the application: the gremium that decides the current vote state
        (``application.vote_gremium_id``) when set, else the ``gremiumId`` of the
        current state, else ``application.gremium_id``. Without that check a
        vote manager of another gremium could run the vote and fire the pass or fail
        branch of the application.

        When neither names a gremium, no gremium can decide on the application. Then
        only the admin role (``admin_bypass`` with ``vote.manage``) creates the vote.
        Otherwise a vote manager of any gremium could fire the branch.

        The caller must also pass ``assert_can_manage_group`` for ``eligibleGroup``.
        This method does not do that check.

        The server sets ``eligible_count`` from the roster of the gremium (members
        with ``vote.cast``). The client cannot send it.

        Only a meeting vote of a public meeting has guests. An unconfirmed guest
        application rests in the flow and gets 404 as on the flow routes, because a vote
        on it could fire its pass or fail branch on close. The proposal amount check
        runs only after the gremium checks, because it would otherwise tell a manager of
        another gremium the requested amount of the application.

        Raises:
            NotFoundError: No application has this id, or its email is not confirmed
                (404).
            ForbiddenError: The application has no gremium and the principal is not
                the admin role (403).
            ValidationProblem: The gremium does not exist (``eligible_group_invalid``)
                or is not the gremium of the application
                (``eligible_group_mismatch``) (422).
        """
        from app.modules.auth.policy import admin_bypass

        if payload.config.guests_vote:
            raise ValidationProblem(
                "Only a vote of a public meeting can include guests.",
                code="guests_vote_unavailable",
                errors=[{"field": "config.guestsVote", "msg": "not a public meeting vote"}],
            )
        gremium_id = payload.eligible_group
        if not await self._gremium_exists(gremium_id):
            raise ValidationProblem(
                "eligibleGroup is not the id of a gremium.",
                code="eligible_group_invalid",
                errors=[{"field": "eligibleGroup", "msg": "unknown gremium"}],
            )
        application = await self._get_application(application_id, confirmed_only=True)
        expected = await self._application_gremium_id(application)
        if expected is None and not admin_bypass(principal, "vote.manage"):
            raise ForbiddenError(
                "the application has no gremium; only the admin role can create a vote"
            )
        if expected is not None and expected != gremium_id:
            raise ValidationProblem(
                "eligibleGroup must be the gremium of the application.",
                code="eligible_group_mismatch",
                errors=[{"field": "eligibleGroup", "msg": "not the gremium of the application"}],
            )
        self._check_proposal(application, payload.proposal)
        from app.modules.livevote.service import MeetingService

        eligible = await MeetingService(self.session).vote_eligible_count(gremium_id)
        internal = VoteCreateInternal(
            config=payload.config,
            eligibleGroup=gremium_id,
            question=payload.question,
            eligibleCount=eligible,
            opensStateId=payload.opens_state_id,
            closesAt=payload.closes_at,
            resultBranchTransitionId=payload.result_branch_transition_id,
            proposal=payload.proposal,
        )
        return await self._insert(application_id, internal)

    async def _gremium_exists(self, gremium_id: UUID) -> bool:
        from app.modules.admin.models import Gremium

        found = await self.session.scalar(select(Gremium.id).where(Gremium.id == gremium_id))
        return found is not None

    async def _application_gremium_id(self, application: Application) -> UUID | None:
        """Return the gremium that decides on the application.

        In a vote state only the snapshot ``vote_gremium_id`` counts. It can be None
        (a vote state with ``gremiumSource: "budget"`` whose Gremium went away); then
        no gremium decides and only the admin role creates a vote. There is no
        fall back to ``application.gremium_id``: that Gremium does not decide here.
        Outside a vote state the ``gremiumId`` of the current state counts when it is
        a valid UUID, else ``application.gremium_id``, which can be None.
        """
        if application.current_state_id is not None:
            from app.modules.flow.models import State

            row = (
                await self.session.execute(
                    select(State.kind, State.config).where(
                        State.id == application.current_state_id
                    )
                )
            ).first()
            if row is not None and row[0] == "vote":
                return application.vote_gremium_id
            config = row[1] if row is not None else None
            ref = config.get("gremiumId") if isinstance(config, dict) else None
            if isinstance(ref, str) and ref:
                try:
                    return UUID(ref)
                except ValueError:
                    pass
        return application.gremium_id

    async def create_internal(
        self,
        application_id: UUID | None,
        payload: VoteCreateInternal,
        *,
        meeting_id: UUID | None = None,
        agenda_item_id: UUID | None = None,
        planned_ok: bool = False,
        actor: str | None = None,
    ) -> VoteOut:
        """Create a draft vote from a server-side payload.

        ``application_id`` is optional. ``None`` marks a generic resolution question of
        a free-text agenda item. Such a vote has no application and fires no flow
        branch on close. ``meeting_id`` binds the vote to a meeting (live vote).
        ``agenda_item_id`` binds it to the agenda item. The caller supplies the
        ``eligible_count`` from the roster and runs the checks.

        A meeting vote locks the meeting row and needs a ``live`` meeting that still
        has the agenda item (see ``_lock_live_meeting``). ``planned_ok`` also accepts
        a ``planned`` meeting, for a vote that is prepared before the start. A poll
        writes ``poll_created`` for ``actor``.

        A decision proposal needs an application, and its amount must fit the
        requested amount.

        Raises:
            NotFoundError: No application has this id, or the agenda item is not in
                the meeting (404).
            ConflictError: The meeting is not ``live``, or not ``planned`` either
                with ``planned_ok`` (409).
            ValidationProblem: A proposal without an application
                (``decision_not_allowed``) or with a bad amount (422).
        """
        if application_id is None and payload.proposal is not None:
            raise not_allowed_problem("Only an application vote takes a decision proposal.")
        if meeting_id is not None:
            await self._lock_live_meeting(
                meeting_id, agenda_item_id=agenda_item_id, planned_ok=planned_ok
            )
        if application_id is not None:
            self._check_proposal(await self._get_application(application_id), payload.proposal)
        return await self._insert(
            application_id,
            payload,
            meeting_id=meeting_id,
            agenda_item_id=agenda_item_id,
            actor=actor,
        )

    async def _insert(
        self,
        application_id: UUID | None,
        payload: VoteCreateInternal,
        *,
        meeting_id: UUID | None = None,
        agenda_item_id: UUID | None = None,
        vote_id: UUID | None = None,
        actor: str | None = None,
    ) -> VoteOut:
        """Write the draft vote and return it with an empty tally.

        ``vote_id`` presets the id (a runoff links its parent in the same commit). A
        poll writes ``poll_created`` for ``actor``.

        The id is preset only when given, because an explicit None would bypass the
        server default.
        """
        election = payload.config if isinstance(payload.config, ElectionConfig) else None
        poll = payload.config if isinstance(payload.config, PollConfig) else None
        kind: VoteKind = "motion"
        if election is not None:
            kind = "election"
        elif poll is not None:
            kind = "poll"
        preset = {"id": vote_id} if vote_id is not None else {}
        vote = Vote(
            **preset,
            kind=kind,
            parent_vote_id=payload.parent_vote_id,
            round=payload.round,
            application_id=application_id,
            meeting_id=meeting_id,
            agenda_item_id=agenda_item_id,
            eligible_group=str(payload.eligible_group),
            question=payload.question,
            config=(
                payload.config.model_dump(by_alias=True)
                if election is None and poll is None
                else payload.config.model_dump(mode="json", by_alias=True)
            ),
            eligible_count=payload.eligible_count,
            opens_state_id=payload.opens_state_id,
            closes_at=payload.closes_at,
            result_branch_transition_id=payload.result_branch_transition_id,
            proposal=payload.proposal.to_json() if payload.proposal is not None else None,
            status="draft",
        )
        self.session.add(vote)
        await self.session.flush()
        if poll is not None:
            await audit_record(
                self.session,
                actor=actor,
                action=AuditAction.POLL_CREATED,
                target_type="vote",
                target_id=str(vote.id),
                data=poll_mod.audit_data(vote, poll),
            )
        await self.session.commit()
        config: VoteConfig
        if election is not None:
            config = election.as_vote_config()
        elif poll is not None:
            config = poll.as_vote_config()
        else:
            config = cast(VoteConfig, payload.config)
        empty = {opt: 0 for opt in config.options}
        return self._to_out(
            vote, config, await self._tally_out(vote, config, empty, vote.eligible_count or 0)
        )

    async def open(
        self,
        vote_id: UUID,
        *,
        now: datetime,
        actor: str | None = None,
        eligible_count: int | None = None,
    ) -> VoteOut:
        """Move the vote from ``draft`` to ``open`` and open the time window.

        ``opens_at`` records the real open time (``openedAt`` in the DTO). The method
        writes a ``vote_open`` audit entry for ``actor``.

        The quorum denominator ``eligible_count`` comes from the authoritative roster.
        The create call sets it. It does NOT come from the logged-in users, because
        that would be fail-open. Without it a percent quorum stays fail-closed and
        never counts as met. A prepared meeting vote waits as a draft while the roster
        can change, so its caller counts the roster again and gives
        ``eligible_count``, which replaces the count of the create.

        A meeting vote opens only in a ``live`` meeting. The method locks the meeting
        row before the vote row, as the meeting close does.

        A vote on an application in a vote state opens only when its Gremium is the
        Gremium that decides that state (``application.vote_gremium_id``). A draft
        made before the application entered the state, or for another Gremium, gives
        409 ``vote_gremium_mismatch``.

        A poll of a Gremium opens only with its end at least one hour ahead. The audit
        entry records ``guestsVote``, because a vote with guests has no quorum.

        Raises:
            ConflictError: The vote is not in ``draft``, its meeting is not ``live``,
                or its Gremium does not decide the vote state of the application.
        """
        meeting_id = await self.session.scalar(select(Vote.meeting_id).where(Vote.id == vote_id))
        if meeting_id is not None:
            await self._lock_live_meeting(meeting_id)
        vote = await self._get_vote(vote_id, for_update=True)
        if vote.status != "draft":
            raise ConflictError(f"vote is {vote.status}, cannot open.", code="conflict")
        if await self.vote_gremium_mismatch(vote):
            raise vote_gremium_mismatch_error()
        await poll_mod.PollService(self).check_open(vote, now)
        config = self._config(vote)
        if eligible_count is not None:
            vote.eligible_count = eligible_count
        vote.opens_at = now
        vote.status = "open"
        data: dict[str, object] = {**self._audit_refs(vote), "guestsVote": config.guests_vote}
        if poll_mod.is_poll(vote):
            data["kind"] = poll_mod.POLL
        await audit_record(
            self.session,
            actor=actor,
            action=AuditAction.VOTE_OPEN,
            target_type="vote",
            target_id=str(vote.id),
            data=data,
        )
        await self.session.flush()
        await self.session.commit()
        empty = {opt: 0 for opt in config.options}
        return self._to_out(
            vote, config, await self._tally_out(vote, config, empty, vote.eligible_count or 0)
        )

    async def cast(
        self,
        vote_id: UUID,
        principal: Principal,
        choice: Choice,
        *,
        now: datetime,
        as_delegation: bool = False,
    ) -> BallotAccepted:
        """Cast a vote.

        ``as_delegation=True`` casts the REPRESENTED vote. It runs under the ``sub`` of
        the delegator. The own vote and the represented vote are two separate ballots.
        This is a transfer, not a duplicate. The unique constraint on (vote, voter)
        protects each ballot on its own.

        The row lock serializes this call against ``close``. The status check and the
        ballot insert share one transaction, so no ballot lands after the tally.

        Voting stays human, so a principal with a scope cap gets 403. ``vote.cast`` sits
        in FORBIDDEN_PERMISSIONS, so no OAuth scope carries it. The group keys carry no
        scope cap, and the delegated ballot reads no permission at all, so the rule
        stands here for both ballots.

        The own ballot checks the roster of the vote, because the router gates only the
        session and external substitutes reach this point. A represented ballot audits
        the use of the delegation. On a later 409 (double vote) the session dependency
        rolls back the transaction, and this entry with it. A member who casts the own
        ballot in a meeting takes part in the meeting.

        Raises:
            ConflictError: 409 - the vote is closed or the voter already voted.
            ForbiddenError: 403 - the voter is not eligible for this vote.
            ValidationProblem: 422 - the choice is not a configured option.
        """
        vote = await self._get_vote(vote_id, for_update=True)
        if vote.status != "open":
            raise ConflictError("vote is not open.", code="conflict")
        if vote.closes_at is not None and now >= vote.closes_at:
            raise ConflictError("voting window has closed.", code="conflict")
        if principal.scope_permissions is not None:
            raise ForbiddenError("Only a human session can cast a ballot.")
        blocked, delegator_sub = await voting_delegation_check(
            self.session, principal.sub, vote.meeting_id, vote.eligible_group, now
        )
        if as_delegation:
            if delegator_sub is None:
                raise ForbiddenError("No delegated voting right for this ballot.")
            voter_sub = delegator_sub
        else:
            if blocked:
                raise ForbiddenError("Voting right has been delegated to another member.")
            if not self._may_cast(principal, vote.eligible_group):
                raise ForbiddenError("Not eligible to vote in this ballot.")
            voter_sub = principal.sub
        config = self._config(vote)
        stored = self._stored_choice(vote, config, choice)
        if as_delegation:
            await audit_record(
                self.session,
                actor=principal.sub,
                action=AuditAction.DELEGATION_USE,
                target_type="vote",
                target_id=str(vote.id),
                data={"eligibleGroup": vote.eligible_group},
            )
        if vote.meeting_id is not None and not as_delegation:
            from app.modules.livevote.attendance_service import AttendanceService

            await AttendanceService(self.session).mark_present_on_cast(
                vote.meeting_id, principal.sub
            )
        if config.secret:
            return await self._cast_secret(vote.id, voter_sub, stored)
        return await self._cast_open(vote.id, voter_sub, stored)

    @staticmethod
    def _stored_choice(vote: Vote, config: VoteConfig, choice: Choice) -> str:
        """Check a ballot against the vote and return its stored form.

        A motion takes one configured option. An election and a poll take their
        own ballot shape (``election.stored_choice``, ``poll.stored_choice``).

        Raises:
            ValidationProblem: The choice does not fit the vote (422).
        """
        if poll_mod.is_poll(vote):
            return poll_mod.stored_choice(poll_mod.poll_config(vote), choice)
        if isinstance(choice, Mapping):
            raise ValidationProblem(
                "Unknown vote option.",
                errors=[{"field": "choice", "msg": "not in vote options"}],
            )
        if election_mod.is_election(vote):
            return election_mod.stored_choice(election_mod.election_config(vote), choice)
        if not isinstance(choice, str) or choice not in config.options:
            raise ValidationProblem(
                "Unknown vote option.",
                errors=[{"field": "choice", "msg": "not in vote options"}],
            )
        return choice

    async def cast_guest(
        self, vote_id: UUID, guest_id: UUID, choice: Choice, *, now: datetime
    ) -> BallotAccepted:
        """Cast the ballot of an admitted guest of a public meeting.

        This is the second, separate eligibility path of ``cast``. A guest is not a
        principal: no ``vote.cast``, no gremium role and no delegation. The caller (the
        public guest service) checks that the guest is admitted, that the meeting lets
        guests vote, and that the vote belongs to a public agenda item of the meeting
        of the guest. This method checks the vote itself: open, in its window, and
        ``guestsVote``. The ballot runs under ``guest:<id>``. The same rules as for a
        member apply: one ballot, never changed after the cast, and a secret
        vote keeps the identity (``voted_marker``) apart from the choice
        (``secret_ballot``). The audit entry ``vote_cast`` names the guest id as the
        actor and carries no choice.

        The audit entry carries ids only, because a secret vote must not link a choice
        to the guest and the chain is append-only.

        Raises:
            ConflictError: 409 - the vote is not open, or the guest already voted.
            ForbiddenError: 403 - the vote is for members only (``vote_members_only``).
            ValidationProblem: 422 - the choice is not a configured option.
        """
        vote = await self._get_vote(vote_id, for_update=True)
        if vote.status != "open":
            raise ConflictError("vote is not open.", code="conflict")
        if vote.closes_at is not None and now >= vote.closes_at:
            raise ConflictError("voting window has closed.", code="conflict")
        config = self._config(vote)
        if not config.guests_vote:
            raise ForbiddenError(
                "Only the members vote in this ballot.", code="vote_members_only"
            )
        stored = self._stored_choice(vote, config, choice)
        voter_sub = guest_voter_sub(guest_id)
        await audit_record(
            self.session,
            actor=voter_sub,
            action=AuditAction.VOTE_CAST,
            target_type="vote",
            target_id=str(vote.id),
            data=self._audit_refs(vote),
        )
        if config.secret:
            return await self._cast_secret(vote.id, voter_sub, stored)
        return await self._cast_open(vote.id, voter_sub, stored)

    @staticmethod
    def _is_gremium_group(eligible_group: str) -> bool:
        """Tell whether ``eligible_group`` names a gremium, that is a UUID as text."""
        try:
            UUID(eligible_group)
        except (ValueError, TypeError):
            return False
        return True

    @staticmethod
    def _may_cast(principal: Principal, eligible_group: str) -> bool:
        """Tell whether the principal may cast an OWN ballot in this vote.

        Only the namespaced key ``vote:<gremium_id>`` decides. `resolve_principal`
        writes it for an active membership whose gremium role carries ``vote.cast``,
        and for nothing else, so the key proves the right. A matching OIDC group claim
        cannot satisfy it. `MeetingService.vote_eligible_count` builds the quorum
        denominator from exactly that roster, so both sides use the same rule.

        A free group key (not a UUID) is an old row. No global permission grants a
        vote right, so such a vote admits nobody.
        """
        if not VotingService._is_gremium_group(eligible_group):
            return False
        return principal.in_group(vote_group_key(eligible_group))

    def can_cast_own(self, vote: Vote, principal: Principal) -> bool:
        """Tell whether the principal may cast an own ballot (the ``canCast`` flag).

        The rule is the roster side of ``cast``: a human session (no OAuth token) and
        ``vote.cast`` in the gremium of the vote. A delegated ballot has its own check.
        """
        return principal.scope_permissions is None and self._may_cast(
            principal, vote.eligible_group
        )

    async def can_still_cast(self, vote: Vote, principal: Principal, *, now: datetime) -> bool:
        """Tell whether `cast` takes a ballot of the principal now, own or represented.

        The rule mirrors the gate of `cast` without a write: the vote is open and its
        window has not ended, the session is human (no OAuth token), and either the
        own ballot (``vote.cast`` in the gremium of the vote, the right not delegated
        away) or the represented ballot (a voting delegation for the meeting) is still
        missing. A ballot that is already in counts as done, because `cast` answers
        409 for it. The task list (`ListingOps.list_tasks`) reads this method.
        """
        if vote.status != "open":
            return False
        if vote.closes_at is not None and now >= vote.closes_at:
            return False
        if principal.scope_permissions is not None:
            return False
        blocked, delegator_sub = await voting_delegation_check(
            self.session, principal.sub, vote.meeting_id, vote.eligible_group, now
        )
        secret = self._config(vote).secret
        if (
            not blocked
            and self._may_cast(principal, vote.eligible_group)
            and not (await self.my_ballot(vote, principal.sub, secret=secret)).cast
        ):
            return True
        if delegator_sub is None:
            return False
        return not (await self.my_ballot(vote, delegator_sub, secret=secret)).cast

    async def _cast_open(self, vote_id: UUID, voter_sub: str, choice: str) -> BallotAccepted:
        """Insert the open ballot. A second cast of the same voter gives 409.

        ``ON CONFLICT DO NOTHING`` keeps the first ballot. An empty ``RETURNING``
        means the voter already voted. A ballot never changes after the cast.

        On a conflict nothing was written, so no rollback is needed: the session
        dependency ``get_session`` ends the transaction on the exception.
        """
        stmt = (
            pg_insert(Ballot)
            .values(vote_id=vote_id, voter_sub=voter_sub, choice=choice)
            .on_conflict_do_nothing(constraint="uq_ballot_vote_voter")
            .returning(Ballot.id)
        )
        inserted = (await self.session.execute(stmt)).first()
        if inserted is None:
            raise ConflictError("Already voted.", code=ALREADY_VOTED)
        await self.session.commit()
        return BallotAccepted(status="cast")

    async def _cast_secret(self, vote_id: UUID, voter_sub: str, choice: str) -> BallotAccepted:
        """Insert the secret ballot. A second cast of the same voter gives 409.

        ``voted_marker`` (UNIQUE) is the "has voted" identity anchor. The method writes
        the identity-less ballot only when the marker is new, so no link from choice to
        voter exists.
        """
        marker = (
            pg_insert(VotedMarker)
            .values(vote_id=vote_id, voter_sub=voter_sub)
            .on_conflict_do_nothing(constraint="uq_voted_marker_vote_voter")
            .returning(VotedMarker.id)
        )
        inserted = (await self.session.execute(marker)).first()
        if inserted is None:
            raise ConflictError("Already voted.", code=ALREADY_VOTED)
        self.session.add(SecretBallot(vote_id=vote_id, choice=choice))
        await self.session.commit()
        return BallotAccepted(status="cast")

    async def assert_can_read(self, vote: Vote, principal: Principal) -> None:
        """Guard read access to a vote (broken object level authorization).

        A meeting-bound vote follows the meeting visibility rules of
        ``MeetingService.assert_can_read``: member, participant, or delegation
        recipient. A vote without a meeting (application vote) is readable with
        ``application.read`` or ``application.read_all`` (the admin role holds both),
        for an eligible voter of the vote, and for a holder of the gremium permission
        ``vote.manage`` or ``session.manage`` in the gremium of the vote. Without this
        check any logged-in user could read the tally of another gremium through
        ``GET /api/votes/{id}``, including closed SECRET votes.

        The admin role reaches this through `Principal.has`, not through a
        `principal.roles` read: `has` is where the OAuth scope cap applies.

        A poll of a Gremium (``kind = poll``, no meeting) is not an application vote,
        so the global application rights do not reach it: only an eligible voter, a
        manager in its Gremium and the admin role (``admin_bypass``) read it.

        Raises:
            ForbiddenError: The principal cannot view this vote.
        """
        if vote.meeting_id is not None:
            from app.modules.livevote.service import MeetingService

            await MeetingService(self.session).assert_can_read(vote.meeting_id, principal)
            return
        if poll_mod.is_poll(vote):
            from app.modules.auth.policy import admin_bypass

            if admin_bypass(principal, "application.read"):
                return
        elif principal.has("application.read") or principal.has("application.read_all"):
            return
        if self._may_cast(principal, vote.eligible_group):
            return
        gremium_id = await self._vote_gremium_id(
            meeting_id=None, eligible_group=vote.eligible_group
        )
        if gremium_id is not None and await holds_gremium_vote_role(
            self.session, gremium_id, principal
        ):
            return
        raise ForbiddenError("not allowed to view this vote")

    async def get_scoped(self, vote_id: UUID, principal: Principal) -> VoteOut:
        """Like ``get`` but fail-closed scoped to the vote's read audience.

        The result carries the ``canManage`` and ``canCast`` flags of the principal,
        the own ballot (``myBallot``) and ``representedCast``.
        """
        vote = await self._get_vote(vote_id)
        await self.assert_can_read(vote, principal)
        out = await self.get(vote_id)
        return out.model_copy(
            update={
                "can_manage": await self.can_manage(vote, principal),
                "can_cast": self.can_cast_own(vote, principal),
                "my_ballot": await self.my_ballot(vote, principal.sub, secret=out.secret),
                "represented_cast": await self.represented_cast(
                    vote, principal.sub, secret=out.secret
                ),
            }
        )

    async def my_ballot(self, vote: Vote, voter_sub: str, *, secret: bool) -> MyBallot:
        """Return the ballot that ``voter_sub`` cast in this vote.

        An open vote reads the ``ballot`` row and returns its choice. A secret vote
        reads only the ``voted_marker``: the choice has no link to the voter, so
        ``choice`` stays None.
        """
        if secret:
            marker = await self.session.scalar(
                select(VotedMarker.id).where(
                    VotedMarker.vote_id == vote.id, VotedMarker.voter_sub == voter_sub
                )
            )
            return MyBallot(cast=marker is not None)
        row = (
            await self.session.execute(
                select(Ballot.choice).where(
                    Ballot.vote_id == vote.id, Ballot.voter_sub == voter_sub
                )
            )
        ).first()
        if row is None:
            return MyBallot(cast=False)
        return election_mod.own_ballot(getattr(vote, "kind", "motion"), row.choice)

    async def represented_cast(self, vote: Vote, sub: str, *, secret: bool) -> bool:
        """Tell whether ``sub`` holds a voting delegation and cast the represented ballot.

        The represented ballot runs under the ``sub`` of the delegator
        (``voting_delegation_check``). The method returns False without an incoming
        voting delegation for the meeting of the vote.
        """
        _, delegator_sub = await voting_delegation_check(
            self.session, sub, vote.meeting_id, vote.eligible_group, datetime.now(UTC)
        )
        if delegator_sub is None:
            return False
        return (await self.my_ballot(vote, delegator_sub, secret=secret)).cast

    async def _vote_gremium_id(
        self, *, meeting_id: UUID | None, eligible_group: str
    ) -> UUID | None:
        """Resolve the gremium of a vote.

        A meeting-bound vote inherits the gremium of the meeting. A vote without a
        meeting (application vote) carries the gremium in ``eligible_group`` as the
        gremium UUID in text form. If ``eligible_group`` is a free group key and not a
        UUID (an old row), no gremium resolves and the method returns ``None``. Only
        the admin role then grants access.
        """
        if meeting_id is not None:
            from app.modules.livevote.models import Meeting

            gid = await self.session.scalar(
                select(Meeting.gremium_id).where(Meeting.id == meeting_id)
            )
            if gid is not None:
                return gid
        try:
            return UUID(eligible_group)
        except (ValueError, TypeError):
            return None

    async def _meeting_grants_vote_management(
        self, meeting_id: UUID, principal: Principal
    ) -> bool:
        """Ask the meeting rule that the client sees as ``canManageVotes``.

        The meeting payload publishes ``canManageVotes``, and the client renders the
        open, close and delete buttons from it. This gate must therefore admit exactly
        the people that flag names, or the UI offers an action that the API refuses.
        ``MeetingService.can_manage_votes`` is the single source of that rule: the
        session manager, the protokollant, or the gremium rule
        (``manages_votes_in_gremium``).

        The protokollant is an active member of the gremium of the meeting, which
        ``_resolve_protokollant`` enforces, so this reaches no other gremium. The same
        people already create, open and delete the votes of the meeting through
        ``/meetings/{id}/votes``, so the close and the cancel add no right that the
        delete does not already carry.
        """
        from app.modules.livevote.models import Meeting
        from app.modules.livevote.service import MeetingService

        meeting = await self.session.get(Meeting, meeting_id)
        if meeting is None:
            return False
        return await MeetingService(self.session).can_manage_votes(meeting, principal)

    async def can_manage_group(
        self, eligible_group: str, meeting_id: UUID | None, principal: Principal
    ) -> bool:
        """Tell whether the principal may manage a vote of this group and meeting.

        The rule is fail-closed and gremium-scoped, symmetric to ``assert_can_read``.
        It covers create, open, close, cancel and delete. The checks run in this
        order:

        1. For a meeting-bound vote, the meeting rule
           (``PermissionOps.can_manage_votes``). It keeps the enforced right equal to
           the advertised ``canManageVotes`` flag, and it holds the gremium rule.
        2. The gremium rule (``manages_votes_in_gremium``) in the gremium of the vote:
           the admin role or a gremium role with ``vote.manage`` or
           ``session.manage``. This covers the application vote that no meeting holds,
           and a vote whose meeting is gone.

        A vote with a free group key resolves no gremium, so only the admin role
        passes.
        """
        if meeting_id is not None and await self._meeting_grants_vote_management(
            meeting_id, principal
        ):
            return True
        gremium_id = await self._vote_gremium_id(
            meeting_id=meeting_id, eligible_group=eligible_group
        )
        if gremium_id is None:
            from app.modules.auth.policy import admin_bypass

            return admin_bypass(principal, "vote.manage")
        return await manages_votes_in_gremium(self.session, gremium_id, principal)

    async def assert_can_manage_group(
        self, eligible_group: str, meeting_id: UUID | None, principal: Principal
    ) -> None:
        """Guard the write and lifecycle access to a vote (``can_manage_group``).

        Raises:
            ForbiddenError: The principal cannot manage this vote.
        """
        if not await self.can_manage_group(eligible_group, meeting_id, principal):
            raise ForbiddenError("not allowed to manage this vote")

    async def can_manage(self, vote: Vote, principal: Principal) -> bool:
        """Like ``can_manage_group`` but for an already-loaded vote.

        A poll of a Gremium (no meeting) takes the right that creates it
        (``PollService.can_create``: ``vote.manage`` or the admin role), so
        ``session.manage`` alone cannot edit, open, close, cancel or delete a poll
        that it cannot create.
        """
        if poll_mod.is_poll(vote) and vote.meeting_id is None:
            gremium_id = await self._vote_gremium_id(
                meeting_id=None, eligible_group=vote.eligible_group
            )
            if gremium_id is None:
                from app.modules.auth.policy import admin_bypass

                return admin_bypass(principal, "vote.manage")
            return await poll_mod.PollService(self).can_create(gremium_id, principal)
        return await self.can_manage_group(vote.eligible_group, vote.meeting_id, principal)

    async def assert_can_manage(self, vote: Vote, principal: Principal) -> None:
        """Like ``assert_can_manage_group`` but for an already-loaded vote (``can_manage``).

        Raises:
            ForbiddenError: The principal cannot manage this vote.
        """
        if not await self.can_manage(vote, principal):
            raise ForbiddenError("not allowed to manage this vote")

    async def meeting_id_of(self, vote_id: UUID) -> UUID | None:
        """Return the meeting of the vote, or None for a vote without a meeting."""
        return await self.session.scalar(select(Vote.meeting_id).where(Vote.id == vote_id))

    async def assert_can_run_vote(self, vote_id: UUID, principal: Principal) -> None:
        """Guard the open and the close of a vote.

        The manage right (``assert_can_manage_vote``) comes first. A vote that a
        meeting holds then needs the protokollant of that meeting
        (``MeetingService.assert_can_run_votes``): the open and the close follow the
        minutes. A vote without a meeting keeps the manage right only.

        Raises:
            NotFoundError: No vote has this id.
            ForbiddenError: The principal cannot manage this vote, or the vote belongs
                to a meeting and the principal is not its protokollant.
        """
        await self.assert_can_manage_vote(vote_id, principal)
        meeting_id = await self.meeting_id_of(vote_id)
        if meeting_id is None:
            return
        from app.modules.livevote.service import MeetingService

        await MeetingService(self.session).assert_can_run_votes(meeting_id, principal)

    async def assert_can_manage_vote(self, vote_id: UUID, principal: Principal) -> None:
        """Load the vote and run ``assert_can_manage`` on it.

        The ``/votes/{id}/{open,close,cancel}`` router calls this before the lifecycle
        call. Open, close and cancel are therefore fail-closed and gremium-scoped like
        ``get_scoped``. The internal live-vote and cron path calls the lifecycle
        methods directly with its own gate. It bypasses this check on purpose.

        Raises:
            NotFoundError: No vote has this id.
            ForbiddenError: The principal cannot manage this vote.
        """
        vote = await self._get_vote(vote_id)
        await self.assert_can_manage(vote, principal)

    async def list_visible(
        self,
        principal: Principal,
        *,
        statuses: Sequence[VoteStatus] | None = None,
        gremium_id: UUID | None = None,
        q: str | None = None,
        kind: VoteKind | None = None,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> Page[VoteListItem]:
        """Return one page of the votes that the principal can read (``GET /votes``).

        The read rule is the rule of ``assert_can_read``, applied in SQL. See
        ``app.modules.voting.listing``.
        """
        from app.modules.voting.listing import list_votes

        return await list_votes(
            self.session,
            principal,
            statuses=statuses,
            gremium_id=gremium_id,
            q=q,
            kind=kind,
            limit=limit,
            offset=offset,
        )

    async def get(self, vote_id: UUID) -> VoteOut:
        """Return the vote state and the aggregated tally.

        A secret vote exposes only the counts and never the voters. This method has no
        scope gate. It is the internal reuse path, for example the tally broadcast
        after ``cast``. The public read endpoint uses ``get_scoped``.

        A revealed open poll shows its running counts, including the "Vielleicht"
        answers. The stored result is text, cast back to ``VoteResult`` because
        ``tally.result`` only writes its Literal values.
        """
        vote = await self._get_vote(vote_id)
        config = self._config(vote)
        counts = await self._aggregate(vote, config)
        tally_out = await self._tally_out(vote, config, counts, vote.eligible_count or 0)
        poll_live: PollResultOut | None = None
        if poll_mod.is_poll(vote) and vote.status == "open" and tally_out.revealed:
            poll_live = poll_mod.result_of(await self._poll_outcome(vote))
        if vote.status == "closed" and vote.result is not None:
            stored_result = cast("tally_mod.VoteResult", vote.result)
            tally_out = tally_out.model_copy(
                update={
                    "result": stored_result,
                    "failed_reason": tally_mod.failed_reason(stored_result, tally_out.quorum_met),
                }
            )
        return self._to_out(vote, config, tally_out, poll_live)

    async def cancel(
        self, vote_id: UUID, *, now: datetime | None = None, actor: str | None = None
    ) -> VoteOut:
        """Move the vote from ``open`` to ``cancelled`` without a result or a branch.

        The application stays in the ``vote`` state. An operator can then create a new
        vote or fire a manual exit. This is the only way out when the vote does not
        reach the quorum, because ``close`` is then blocked. The method sets
        ``closed_at`` and writes a ``vote_cancel`` audit entry for ``actor``.

        Raises:
            ConflictError: The vote is not open.
        """
        vote = await self._get_vote(vote_id, for_update=True)
        if vote.status != "open":
            raise ConflictError(f"vote is {vote.status}, cannot cancel.", code="conflict")
        await self._mark_cancelled(
            vote, now=now or datetime.now(UTC), actor=actor, reason="manual"
        )
        await self.session.commit()
        config = self._config(vote)
        counts = await self._aggregate(vote, config)
        return self._to_out(
            vote,
            config,
            await self._tally_out(vote, config, counts, vote.eligible_count or 0),
        )

    async def _mark_cancelled(
        self, vote: Vote, *, now: datetime, actor: str | None, reason: str
    ) -> None:
        """Set a loaded vote to ``cancelled`` and audit it, without a commit.

        A cancelled runoff releases its link, so it no longer blocks a new runoff of its
        election.
        """
        previous = vote.status
        vote.status = "cancelled"
        vote.closed_at = now
        await election_mod.release_runoff_link(self.session, vote)
        await audit_record(
            self.session,
            actor=actor,
            action=AuditAction.VOTE_CANCEL,
            target_type="vote",
            target_id=str(vote.id),
            data={**self._audit_refs(vote), "reason": reason, "previousStatus": previous},
        )

    async def cancel_for_application(
        self,
        application_id: UUID,
        *,
        now: datetime,
        actor: str | None = None,
        left_state_id: UUID | None = None,
        entered_state_id: UUID | None = None,
    ) -> list[Vote]:
        """Cancel the votes that a state change of the application orphans.

        The flow calls this when the application leaves its state without a vote
        branch: a transition without a branch, a forced status, or an audit revert.

        * Every ``open`` vote of the application is cancelled.
        * A ``draft`` vote is cancelled only when it belongs to the state that the
          application leaves (``left_state_id``). That is a draft whose
          ``opens_state_id`` is the left state, or a draft without ``opens_state_id``
          when the left state is a vote state.
        * Every other draft stays. Examples: a draft without ``opens_state_id`` that
          was prepared before the application enters its vote state, or a draft for a
          later vote state. A transition back into the same state keeps every draft.

        Each cancelled vote gets ``closed_at`` and a ``vote_cancel`` audit entry.

        The method does not commit. The caller commits together with the state change
        and then sends ``vote_cancelled`` for the returned votes.

        Returns:
            The cancelled votes.
        """
        rows = (
            (
                await self.session.execute(
                    select(Vote)
                    .where(
                        Vote.application_id == application_id,
                        Vote.status.in_(("open", "draft")),
                    )
                    .order_by(Vote.created_at)
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        left_is_vote: bool | None = None
        cancelled: list[Vote] = []
        for vote in rows:
            if vote.status == "draft":
                if left_state_id is None or left_state_id == entered_state_id:
                    continue
                if vote.opens_state_id is None:
                    if left_is_vote is None:
                        left_is_vote = await self._is_vote_state(left_state_id)
                    if not left_is_vote:
                        continue
                elif vote.opens_state_id != left_state_id:
                    continue
            await self._mark_cancelled(vote, now=now, actor=actor, reason="state_left")
            cancelled.append(vote)
        await self.session.flush()
        return cancelled

    async def _is_vote_state(self, state_id: UUID) -> bool:
        """Tell if the state is a vote state.

        A vote state has ``kind == 'vote'`` or at least one ``pass``/``fail`` branch
        exit.
        """
        from app.modules.flow.models import State, Transition

        kind = await self.session.scalar(select(State.kind).where(State.id == state_id))
        if kind == "vote":
            return True
        branch = await self.session.scalar(
            select(Transition.id)
            .where(Transition.from_state_id == state_id, Transition.branch.is_not(None))
            .limit(1)
        )
        return branch is not None

    async def cancel_drafts_for_meeting(
        self,
        meeting_id: UUID,
        *,
        now: datetime,
        actor: str | None = None,
        reason: str = "meeting_closed",
    ) -> list[Vote]:
        """Cancel the ``draft`` votes of a meeting, without a commit.

        The meeting close uses this: a draft of a closed meeting can never open. Each
        vote gets ``closed_at`` and a ``vote_cancel`` audit entry with ``reason``
        (default ``meeting_closed``). The meeting delete does not cancel: it deletes
        the votes (``delete_for_meeting``).

        Returns:
            The cancelled votes.
        """
        rows = (
            (
                await self.session.execute(
                    select(Vote)
                    .where(Vote.meeting_id == meeting_id, Vote.status == "draft")
                    .order_by(Vote.created_at)
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        for vote in rows:
            await self._mark_cancelled(vote, now=now, actor=actor, reason=reason)
        await self.session.flush()
        return list(rows)

    async def close(
        self, vote_id: UUID, principal: Principal, *, now: datetime | None = None
    ) -> VoteClosed:
        """Close an open vote, compute the tally and the result, then fire the branch.

        One transaction, one commit. The method stages the tally result,
        ``status=closed`` and ``closed_at``, and a ``vote_close`` audit entry. It then
        stages the ``pass`` or ``fail`` transition of the application in a SAVEPOINT.
        The commit writes the close and the transition together.

        A blocked branch does not block the close. When the guard of the transition
        fails, another transition wins the race, or the current state has no such
        transition, only the SAVEPOINT rolls back. The vote stays closed, the audit log
        gets ``vote_branch_blocked`` (vote, branch, reason), and the application stays
        in its state. ``branchFired`` is then False, and a person must move the
        application by hand. The cron therefore never retries a closed vote.

        An expired quorum vote is a special case. Such a vote is time-bound and
        quorum-gated, and its window ``closes_at`` passed with the quorum unmet. It has
        finally failed, because no more ballots are possible. On a manual close
        (``now=None``) the fail-closed 409 applies. If the caller (cron) passes ``now``
        and the window already expired, the close marks the vote as terminal
        QUORUM-MISSED and fires the ``fail`` branch. Without that rule the application
        would hang in the ``vote`` state forever.

        The window expiry counts only when the caller (cron) passes ``now``. An expired
        quorum forces ``rejected``, so the ``fail`` branch fires.

        A meeting vote fixes its attendance at the close. For a vote with guests the
        number of eligible voters is the present members plus the admitted guests at
        this moment, because a guest admitted while the vote ran voted too. It is a
        display value only, because such a vote has no quorum.

        A ``vote`` state has two fixed exits: ``passed`` fires ``pass``; ``rejected``
        and ``tie`` are fail-closed and fire ``fail``. A generic resolution question has
        no application and fires no branch. It only holds the result for the protocol.
        The audit entry holds aggregates only, never a voter. The status event of a
        fired branch carries the decision for the timeline and the revert.

        Raises:
            ConflictError: The vote is not open, or the quorum is not met before the
                window expired.
        """
        vote = await self._get_vote(vote_id, for_update=True)
        if vote.status != "open":
            raise ConflictError(f"vote is {vote.status}, cannot close.", code="conflict")
        if election_mod.is_election(vote):
            return await self._close_election(vote, principal, now=now)
        if poll_mod.is_poll(vote):
            return await self._close_poll(vote, principal, now=now)
        config = self._config(vote)
        counts = await self._aggregate(vote, config)
        eligible = vote.eligible_count or 0
        outcome = tally_mod.result(config, counts, eligible)

        window_expired = (
            now is not None and vote.closes_at is not None and now >= vote.closes_at
        )

        if not outcome.quorum_met and not window_expired:
            raise ConflictError(
                "quorum not met — the vote cannot be closed; collect more ballots "
                "or cancel the vote.",
                code="conflict",
            )

        result_value: tally_mod.VoteResult = (
            outcome.result if outcome.quorum_met else "rejected"
        )
        closed_at = now or datetime.now(UTC)

        if vote.meeting_id is not None:
            members = await self._present_count(vote)
            guests = await self._guest_attendance(vote, config)
            vote.present_members = members
            vote.present_guests = guests
            if config.guests_vote:
                eligible = members + guests
                vote.eligible_count = eligible

        vote.status = "closed"
        vote.result = result_value
        vote.closed_at = closed_at
        await audit_record(
            self.session,
            actor=principal.sub,
            action=AuditAction.VOTE_CLOSE,
            target_type="vote",
            target_id=str(vote.id),
            data={
                **self._audit_refs(vote),
                "result": result_value,
                "counts": dict(counts),
                "quorumMet": outcome.quorum_met,
            },
        )

        branch_name = "pass" if result_value == "passed" else "fail"
        flow = FlowService(self.session, self.dispatcher)
        staged: StagedFire | None = None
        decision: ApplicationDecision | None = None
        if vote.application_id is not None:
            staged, decision = await self._stage_branch(
                flow,
                vote,
                vote.application_id,
                branch_name,
                principal,
                note=f"vote:{result_value}",
                decide=result_value == "passed",
            )
        if staged is not None:
            vote.result_branch_transition_id = staged.transition.id
            if decision is not None:
                decision.status_event_id = staged.status_event_id
        await self.session.commit()

        new_state_id: UUID | None = None
        if staged is not None:
            fired = await flow.after_commit(staged)
            new_state_id = fired.new_state_id

        tally_out = TallyOut(
            counts=counts,
            eligible=eligible,
            quorumMet=outcome.quorum_met,
            leading=outcome.leading,
            result=result_value,
            failedReason=tally_mod.failed_reason(result_value, outcome.quorum_met),
            presentMembers=getattr(vote, "present_members", None),
            presentGuests=getattr(vote, "present_guests", None),
        )
        return VoteClosed(
            id=vote.id,
            meetingId=vote.meeting_id,
            applicationId=vote.application_id,
            result=result_value,
            tally=tally_out,
            closedAt=closed_at,
            firedTransitionId=staged.transition.id if staged is not None else None,
            newStateId=new_state_id,
            branchFired=staged is not None,
        )

    async def _record_proposal(
        self, vote: Vote, application_id: UUID, principal: Principal
    ) -> ApplicationDecision | None:
        """Write the proposal of a passed vote as the decision of its application.

        A vote without a proposal writes nothing. When the application amount went
        below the approved amount after the vote opened, the decision binds the
        requested amount (``approvedAmount`` null) and keeps the conditions.
        """
        proposal = DecisionIn.from_stored(getattr(vote, "proposal", None))
        if proposal is None:
            return None
        application = await self._get_application(application_id)
        approved = proposal.approved_amount
        if approved is not None and (application.amount is None or approved > application.amount):
            proposal = proposal.model_copy(update={"approved_amount": None})
        return await record_decision(
            self.session,
            application,
            proposal,
            actor=principal.sub,
            decided_by=None,
            old_approved=application.approved_amount,
            vote_id=vote.id,
        )

    async def _close_election(
        self, vote: Vote, principal: Principal, *, now: datetime | None
    ) -> VoteClosed:
        """Close a locked, open election: tally, store the result, no flow branch.

        The quorum rule is the rule of a motion: a manual close with the quorum missed
        gives 409; the cron close after the window ends stores ``rejected``. The tally
        decides ``elected``, ``runoff`` (a runoff decides the open seats), ``tie`` (the
        lot decides) or ``rejected``. The audit entry holds aggregates only.

        A meeting election fixes its attendance at the close, as a motion does.

        Raises:
            ConflictError: The quorum is missed and the window has not expired.
        """
        config = self._config(vote)
        eligible = vote.eligible_count or 0
        outcome = await self._election_outcome(vote, eligible)
        window_expired = (
            now is not None and vote.closes_at is not None and now >= vote.closes_at
        )
        if not outcome.quorum_met and not window_expired:
            raise ConflictError(
                "quorum not met — the vote cannot be closed; collect more ballots "
                "or cancel the vote.",
                code="conflict",
            )
        closed_at = now or datetime.now(UTC)
        if vote.meeting_id is not None:
            members = await self._present_count(vote)
            guests = await self._guest_attendance(vote, config)
            vote.present_members = members
            vote.present_guests = guests
            if config.guests_vote:
                eligible = members + guests
                vote.eligible_count = eligible
        result = election_mod.result_of(outcome)
        vote.status = "closed"
        vote.result = outcome.result
        vote.closed_at = closed_at
        vote.election_result = election_mod.dump_result(result)
        await audit_record(
            self.session,
            actor=principal.sub,
            action=AuditAction.VOTE_CLOSE,
            target_type="vote",
            target_id=str(vote.id),
            data={
                **self._audit_refs(vote),
                "kind": "election",
                "result": outcome.result,
                "counts": outcome.display_counts(),
                "elected": list(outcome.elected),
                "quorumMet": outcome.quorum_met,
            },
        )
        await self.session.commit()
        tally_out = TallyOut(
            counts=outcome.display_counts(),
            eligible=eligible,
            voted=outcome.ballots,
            quorumMet=outcome.quorum_met,
            result=outcome.result,
            failedReason=None if outcome.quorum_met else "quorum",
            presentMembers=vote.present_members if vote.meeting_id is not None else None,
            presentGuests=vote.present_guests if vote.meeting_id is not None else None,
        )
        return VoteClosed(
            id=vote.id,
            meetingId=vote.meeting_id,
            applicationId=None,
            result=outcome.result,
            tally=tally_out,
            closedAt=closed_at,
            kind="election",
            electionResult=result,
        )

    async def _close_poll(
        self, vote: Vote, principal: Principal, *, now: datetime | None
    ) -> VoteClosed:
        """Close a locked, open poll: count, store ``poll_result``, keep ``result`` NULL.

        A poll has no quorum and no majority, so a close never fails on the count and
        fires no flow branch. A meeting poll fixes the attendance, as a vote does. The
        audit entry holds aggregates only.
        """
        config = self._config(vote)
        outcome = await self._poll_outcome(vote)
        eligible = vote.eligible_count or 0
        closed_at = now or datetime.now(UTC)
        if vote.meeting_id is not None:
            members = await self._present_count(vote)
            guests = await self._guest_attendance(vote, config)
            vote.present_members = members
            vote.present_guests = guests
            if config.guests_vote:
                eligible = members + guests
                vote.eligible_count = eligible
        result = poll_mod.result_of(outcome)
        vote.status = "closed"
        vote.result = None
        vote.closed_at = closed_at
        vote.poll_result = poll_mod.dump_result(result)
        await audit_record(
            self.session,
            actor=principal.sub,
            action=AuditAction.VOTE_CLOSE,
            target_type="vote",
            target_id=str(vote.id),
            data={
                **self._audit_refs(vote),
                "kind": poll_mod.POLL,
                "counts": outcome.display_counts(),
                "ballots": outcome.ballots,
            },
        )
        await self.session.commit()
        tally_out = TallyOut(
            counts=outcome.display_counts(),
            eligible=eligible,
            voted=outcome.ballots,
            quorumMet=True,
            presentMembers=vote.present_members if vote.meeting_id is not None else None,
            presentGuests=vote.present_guests if vote.meeting_id is not None else None,
        )
        return VoteClosed(
            id=vote.id,
            meetingId=vote.meeting_id,
            applicationId=None,
            result=None,
            tally=tally_out,
            closedAt=closed_at,
            kind="poll",
            pollResult=result,
        )

    async def _stage_branch(
        self,
        flow: FlowService,
        vote: Vote,
        application_id: UUID,
        branch_name: str,
        principal: Principal,
        *,
        note: str,
        decide: bool = False,
    ) -> tuple[StagedFire | None, ApplicationDecision | None]:
        """Stage the result branch in a SAVEPOINT, or audit why it is blocked.

        The SAVEPOINT keeps the staged vote close safe: a guard failure, a lost race or
        a missing branch transition rolls back only the branch. The method then writes
        ``vote_branch_blocked`` and returns no staged fire.

        Defence in depth: a vote whose Gremium does not decide the current vote state
        of the application (``application.vote_gremium_id``) never fires the branch,
        reason ``vote_gremium_mismatch``. An example is a stale agenda item of a
        meeting of another Gremium. Such a vote also writes no decision.

        ``decide`` (a passed vote) writes the proposal of the vote as the decision of
        the application before the SAVEPOINT. The guard `budgetFitsApplication`
        of the branch then checks the approved amount, and a blocked branch keeps the
        decision of the vote.

        A current state without the branch (a misconfigured flow, or a vote outside its
        vote state) gives the reason ``no_branch``.
        """
        reason: str | None = None
        decision: ApplicationDecision | None = None
        if await self.vote_gremium_mismatch(vote):
            reason = VOTE_GREMIUM_MISMATCH
        else:
            if decide:
                decision = await self._record_proposal(vote, application_id, principal)
            try:
                async with self.session.begin_nested():
                    staged = await flow.stage_branch(
                        application_id, branch_name, principal, note=note, vote_id=vote.id
                    )
                    return staged, decision
            except ConflictError as exc:
                reason = exc.code
            except NotFoundError:
                reason = "no_branch"
        await audit_record(
            self.session,
            actor=principal.sub,
            action=AuditAction.VOTE_BRANCH_BLOCKED,
            target_type="vote",
            target_id=str(vote.id),
            data={**self._audit_refs(vote), "branch": branch_name, "reason": reason},
        )
        return None, decision

    async def vote_gremium_mismatch(self, vote: Vote) -> bool:
        """Tell whether the Gremium of ``vote`` does not decide its application now.

        The check applies only while the application sits in a ``vote`` state. The
        Gremium of the vote (the meeting Gremium, else ``eligible_group``) must be the
        snapshot ``application.vote_gremium_id``. A missing snapshot counts as a
        mismatch (fail closed). A vote without an application, and an application
        outside a vote state, give False: nothing fires a branch there.
        """
        if vote.application_id is None:
            return False
        from app.modules.flow.models import State

        row = (
            await self.session.execute(
                select(Application.vote_gremium_id, State.kind)
                .join(State, State.id == Application.current_state_id)
                .where(Application.id == vote.application_id)
            )
        ).first()
        if row is None or row[1] != "vote":
            return False
        actual = await self._vote_gremium_id(
            meeting_id=vote.meeting_id, eligible_group=vote.eligible_group
        )
        return row[0] is None or actual != row[0]
