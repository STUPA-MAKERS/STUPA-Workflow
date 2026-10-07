"""Voting service: create -> open -> cast -> close (or cancel).

Race safety: the DB enforces one ballot per voter. A ballot never changes after the
cast (O11).

* open (``secret=false``): ``INSERT ... ON CONFLICT (vote_id, voter_sub) DO NOTHING``.
  An empty ``RETURNING`` means a second cast -> 409 ``already_voted``.
* secret (``secret=true``): ``voted_marker`` (UNIQUE) records 'has voted'. The ballot
  lands without an identity in ``secret_ballot``. A second cast gives 409
  ``already_voted`` too.

Close and cancel set ``closed_at``. Open, close and cancel write an audit entry
(F12). A close always ends the vote: when the pass or fail transition of the
application cannot fire, the close still commits, writes ``vote_branch_blocked`` and
returns ``branchFired=false`` (F20).

RBAC is fail-closed and gremium-scoped. ``vote.eligible_group`` holds the UUID of the
gremium that votes. A ``cast`` needs the gremium permission ``vote.cast`` there: only an
active gremium role with ``vote.cast`` writes the namespaced group key
``vote:<gremium_id>``. No global permission grants a vote right. The quorum denominator
(``MeetingService.vote_eligible_count``) reads the same roster, and ``create`` stores it
as ``eligible_count``, so the counted set and the admitted set stay equal. A vote with a
free group key (an old row) admits nobody: the call gets 403.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.applications.models import Application, StatusEvent
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.auth.principal import Principal
from app.modules.auth.rbac import vote_group_key
from app.modules.delegations.service import voting_delegation_check
from app.modules.flow.dispatch import ActionDispatcher, NullActionDispatcher
from app.modules.flow.service import FlowService, StagedFire
from app.modules.protocol.models import ProtocolVoteRef
from app.modules.voting import tally as tally_mod
from app.modules.voting.models import Ballot, SecretBallot, Vote, VotedMarker
from app.modules.voting.schemas import (
    BallotAccepted,
    MyBallot,
    TallyOut,
    VoteClosed,
    VoteCreate,
    VoteCreateInternal,
    VoteListItem,
    VoteOut,
    VoteStatus,
)
from app.shared.config_schemas import VoteConfig
from app.shared.errors import ConflictError, ForbiddenError, NotFoundError, ValidationProblem
from app.shared.paging import DEFAULT_LIMIT, Page

# The problem code of a second cast (REST 409 and the live-vote error frame).
ALREADY_VOTED = "already_voted"

# 409 code and audit reason: the Gremium of a vote does not decide the current vote
# state of its application (`application.vote_gremium_id`).
VOTE_GREMIUM_MISMATCH = "vote_gremium_mismatch"


def vote_gremium_mismatch_error() -> ConflictError:
    """Build the 409 for a vote of a Gremium that does not decide the application."""
    return ConflictError(
        "The Gremium of this vote does not decide the current vote of the application.",
        code=VOTE_GREMIUM_MISMATCH,
    )
# The voter key of a guest of a public meeting (#17): ``guest:<meeting_guest.id>``. A
# guest is not a principal, so the key never collides with an OIDC ``sub``.
GUEST_VOTER_PREFIX = "guest:"


def guest_voter_sub(guest_id: UUID) -> str:
    """Return the ``voter_sub`` of a guest ballot (#17)."""
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


class VotingService:
    """Vote service on one ``AsyncSession`` with an optional flow dispatcher."""

    def __init__(self, session: AsyncSession, dispatcher: ActionDispatcher | None = None) -> None:
        self.session = session
        self.dispatcher: ActionDispatcher = dispatcher or NullActionDispatcher()

    async def _get_vote(self, vote_id: UUID, *, for_update: bool = False) -> Vote:
        """Load a vote by id.

        ``for_update`` locks the row and serializes cast against close. Without the
        lock a last-second ballot could commit between the tally and ``status=closed``,
        and then be missing from the recorded result.

        Raises:
            NotFoundError: No vote has this id.
        """
        stmt = select(Vote).where(Vote.id == vote_id)
        if for_update:
            # A locked read must see the committed values, not a stale identity-map
            # copy from an earlier unlocked read in this transaction.
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        vote = (await self.session.execute(stmt)).scalar_one_or_none()
        if vote is None:
            raise NotFoundError(f"vote {vote_id} not found")
        return vote

    async def _lock_live_meeting(
        self, meeting_id: UUID, *, agenda_item_id: UUID | None = None
    ) -> None:
        """Lock the meeting row and require a ``live`` meeting (O12, O25).

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
        # Local import: the livevote models import this module.
        from app.modules.livevote.models import Meeting, MeetingAgendaItem

        status = await self.session.scalar(
            select(Meeting.status).where(Meeting.id == meeting_id).with_for_update()
        )
        if status is None:
            raise NotFoundError(f"meeting {meeting_id} not found")
        if status == "planned":
            raise ConflictError(
                "The meeting has not started. Start it before opening a vote.",
                code="meeting_not_started",
            )
        if status != "live":
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
        """Delete a meeting-bound vote and write a ``vote_delete`` audit entry (O24).

        The ballots cascade through the foreign key. The method deletes only a vote of
        this meeting, and only a ``draft`` or ``cancelled`` vote. An open or closed
        vote is part of the record of the meeting, and a closed result may already
        have fired a flow branch. The same rule keeps an agenda item with such a vote
        (O25), so two deletes cannot get around it. The caller cancels an open vote
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

        The agenda-item remove calls this first (F24, O25). The foreign key
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
        if any(vote.status == "open" for vote in rows):
            raise ConflictError(
                "a vote of this meeting is still open — close or cancel it first",
                code="open_vote",
            )
        ids = [vote.id for vote in rows]
        if ids:
            for model in (ProtocolVoteRef, SecretBallot, VotedMarker, Ballot):
                await self.session.execute(delete(model).where(model.vote_id.in_(ids)))
            await self.session.execute(
                update(StatusEvent).where(StatusEvent.vote_id.in_(ids)).values(vote_id=None)
            )
        for vote in rows:
            await self._delete_audited(vote, actor=actor, reason="meeting_deleted")
        return ids

    async def _delete_audited(
        self, vote: Vote, *, actor: str, reason: str | None = None
    ) -> None:
        """Write ``vote_delete`` for a loaded vote and delete it, without a commit.

        ``reason`` names a delete that another delete caused (``meeting_deleted``).
        """
        data: dict[str, str | None] = {
            **self._audit_refs(vote),
            "agendaItemId": str(vote.agenda_item_id) if vote.agenda_item_id else None,
            "status": vote.status,
        }
        if reason is not None:
            data["reason"] = reason
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
        if config.secret:
            choices: Sequence[str | None] = (
                (
                    await self.session.execute(
                        select(SecretBallot.choice).where(SecretBallot.vote_id == vote.id)
                    )
                )
                .scalars()
                .all()
            )
        else:
            choices = (
                (await self.session.execute(select(Ballot.choice).where(Ballot.vote_id == vote.id)))
                .scalars()
                .all()
            )
        return tally_mod.tally(config.options, choices)

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
        """Count the admitted guests of the meeting of the vote (#17), or 0 without one."""
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
        """Count the guests of a vote (#17).

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

        A vote with guests (#17) counts the admitted guests as present too: they are
        expected ballots. ``presentMembers`` and ``presentGuests`` give the attendance
        of a meeting vote, live while it runs and fixed after the close.
        """
        voted = sum(counts.values())
        outcome = tally_mod.result(config, counts, eligible)
        members: int | None = None
        guests: int | None = None
        # Query the present denominator only when it changes the reveal decision, that
        # is for an open vote with a meeting. A closed vote or a vote without a meeting
        # needs no query.
        if vote.status == "closed":
            present, revealed = 0, True
            members = getattr(vote, "present_members", None)
            guests = getattr(vote, "present_guests", None)
        elif vote.meeting_id is None:
            # A secret vote never reveals a running tally, with or without a meeting.
            present, revealed = 0, not config.secret
        else:
            members = await self._present_count(vote)
            guests = await self._guest_attendance(vote, config)
            present = members + guests if config.guests_vote else members
            if config.secret:
                revealed = False
            else:
                # The expected votes are the present members (and guests) plus the
                # represented votes of absent delegators. Without them the interim
                # count leaks too early.
                expected = present + await self._absent_delegated_count(vote)
                revealed = open_tally_revealed(present, voted, expected)
        return TallyOut(
            counts=counts if revealed else {},
            eligible=eligible,
            voted=voted,
            present=present,
            revealed=revealed,
            quorumMet=outcome.quorum_met,
            leading=outcome.leading if revealed else None,
            result=None,
            presentMembers=members,
            presentGuests=guests,
        )

    def _to_out(self, vote: Vote, config: VoteConfig, tally_out: TallyOut) -> VoteOut:
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
        )

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

        Raises:
            NotFoundError: No application has this id, or its email is not confirmed
                (404).
            ForbiddenError: The application has no gremium and the principal is not
                the admin role (403).
            ValidationProblem: The gremium does not exist (``eligible_group_invalid``)
                or is not the gremium of the application
                (``eligible_group_mismatch``) (422).
        """
        from app.modules.admin.gremium_roles import admin_bypass

        if payload.config.guests_vote:
            # Only a meeting vote of a public meeting has guests (#17).
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
        # An unconfirmed guest application rests in the flow. A vote on it could fire
        # its pass or fail branch on close, so it gets 404 as on the flow routes.
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
        # Local import: `app.modules.livevote.service` imports this module.
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
    ) -> VoteOut:
        """Create a draft vote from a server-side payload.

        ``application_id`` is optional. ``None`` marks a generic resolution question of
        a free-text agenda item. Such a vote has no application and fires no flow
        branch on close. ``meeting_id`` binds the vote to a meeting (live vote).
        ``agenda_item_id`` binds it to the agenda item. The caller supplies the
        ``eligible_count`` from the roster and runs the checks.

        A meeting vote locks the meeting row and needs a ``live`` meeting that still
        has the agenda item (see ``_lock_live_meeting``).

        Raises:
            NotFoundError: No application has this id, or the agenda item is not in
                the meeting (404).
            ConflictError: The meeting is not ``live`` (409).
        """
        if meeting_id is not None:
            await self._lock_live_meeting(meeting_id, agenda_item_id=agenda_item_id)
        if application_id is not None:
            await self._get_application(application_id)
        return await self._insert(
            application_id, payload, meeting_id=meeting_id, agenda_item_id=agenda_item_id
        )

    async def _insert(
        self,
        application_id: UUID | None,
        payload: VoteCreateInternal,
        *,
        meeting_id: UUID | None = None,
        agenda_item_id: UUID | None = None,
    ) -> VoteOut:
        """Write the draft vote and return it with an empty tally."""
        vote = Vote(
            application_id=application_id,
            meeting_id=meeting_id,
            agenda_item_id=agenda_item_id,
            eligible_group=str(payload.eligible_group),
            question=payload.question,
            config=payload.config.model_dump(by_alias=True),
            eligible_count=payload.eligible_count,
            opens_state_id=payload.opens_state_id,
            closes_at=payload.closes_at,
            result_branch_transition_id=payload.result_branch_transition_id,
            status="draft",
        )
        self.session.add(vote)
        await self.session.flush()
        await self.session.commit()
        config = payload.config
        empty = {opt: 0 for opt in config.options}
        return self._to_out(
            vote, config, await self._tally_out(vote, config, empty, vote.eligible_count or 0)
        )

    async def open(
        self, vote_id: UUID, *, now: datetime, actor: str | None = None
    ) -> VoteOut:
        """Move the vote from ``draft`` to ``open`` and open the time window.

        ``opens_at`` records the real open time (``openedAt`` in the DTO). The method
        writes a ``vote_open`` audit entry for ``actor``.

        The quorum denominator ``eligible_count`` comes from the authoritative roster.
        The create call sets it. It does NOT come from the logged-in users, because
        that would be fail-open. Without it a percent quorum stays fail-closed and
        never counts as met.

        A meeting vote opens only in a ``live`` meeting. The method locks the meeting
        row before the vote row, as the meeting close does (O12).

        A vote on an application in a vote state opens only when its Gremium is the
        Gremium that decides that state (``application.vote_gremium_id``). A draft
        made before the application entered the state, or for another Gremium, gives
        409 ``vote_gremium_mismatch``.

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
        config = self._config(vote)
        vote.opens_at = now
        vote.status = "open"
        await audit_record(
            self.session,
            actor=actor,
            action=AuditAction.VOTE_OPEN,
            target_type="vote",
            target_id=str(vote.id),
            # #17: a vote with guests has no quorum; the log keeps that rule.
            data={**self._audit_refs(vote), "guestsVote": config.guests_vote},
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
        choice: str,
        *,
        now: datetime,
        as_delegation: bool = False,
    ) -> BallotAccepted:
        """Cast a vote.

        ``as_delegation=True`` casts the REPRESENTED vote. It runs under the ``sub`` of
        the delegator. The own vote and the represented vote are two separate ballots.
        This is a transfer, not a duplicate. The unique constraint on (vote, voter)
        protects each ballot on its own.

        Raises:
            ConflictError: 409 - the vote is closed or the voter already voted.
            ForbiddenError: 403 - the voter is not eligible for this vote.
            ValidationProblem: 422 - the choice is not a configured option.
        """
        # The row lock serializes this call against close(). The status check and the
        # ballot insert share one transaction, so no ballot lands after the tally.
        vote = await self._get_vote(vote_id, for_update=True)
        if vote.status != "open":
            raise ConflictError("vote is not open.", code="conflict")
        if vote.closes_at is not None and now >= vote.closes_at:
            raise ConflictError("voting window has closed.", code="conflict")
        # Voting stays human. `vote.cast` sits in FORBIDDEN_PERMISSIONS, so no OAuth
        # scope ever carries it. The group keys carry no scope cap, and the delegated
        # ballot reads no permission at all, so the rule stands here for both ballots.
        if principal.scope_permissions is not None:
            raise ForbiddenError("Only a human session can cast a ballot.")
        # `blocked` means the caller delegated the own voting right for THIS meeting.
        # `delegator_sub` holds the sub whose voting right the caller received, or None.
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
            # Own vote: the roster of the vote decides. The router gates only the
            # session, so external substitutes reach this point.
            if not self._may_cast(principal, vote.eligible_group):
                raise ForbiddenError("Not eligible to vote in this ballot.")
            voter_sub = principal.sub
        config = self._config(vote)
        if choice not in config.options:
            raise ValidationProblem(
                "Unknown vote option.",
                errors=[{"field": "choice", "msg": "not in vote options"}],
            )
        if as_delegation:
            # Audit the USE of the delegation. On a later 409 (double vote) the session
            # dependency rolls back the transaction, and this entry with it.
            await audit_record(
                self.session,
                actor=principal.sub,
                action=AuditAction.DELEGATION_USE,
                target_type="vote",
                target_id=str(vote.id),
                data={"eligibleGroup": vote.eligible_group},
            )
        if config.secret:
            return await self._cast_secret(vote.id, voter_sub, choice)
        return await self._cast_open(vote.id, voter_sub, choice)

    async def cast_guest(
        self, vote_id: UUID, guest_id: UUID, choice: str, *, now: datetime
    ) -> BallotAccepted:
        """Cast the ballot of an admitted guest of a public meeting (#17).

        This is the second, separate eligibility path of ``cast``. A guest is not a
        principal: no ``vote.cast``, no gremium role and no delegation. The caller (the
        public guest service) checks that the guest is admitted, that the meeting lets
        guests vote, and that the vote belongs to a public agenda item of the meeting
        of the guest. This method checks the vote itself: open, in its window, and
        ``guestsVote``. The ballot runs under ``guest:<id>``. The same rules as for a
        member apply: one ballot, never changed after the cast (O11), and a secret
        vote keeps the identity (``voted_marker``) apart from the choice
        (``secret_ballot``). The audit entry ``vote_cast`` names the guest id as the
        actor and carries no choice.

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
        if choice not in config.options:
            raise ValidationProblem(
                "Unknown vote option.",
                errors=[{"field": "choice", "msg": "not in vote options"}],
            )
        voter_sub = guest_voter_sub(guest_id)
        # Ids only, never the choice: a secret vote must not link a choice to the
        # guest, and the chain is append-only.
        await audit_record(
            self.session,
            actor=voter_sub,
            action=AuditAction.VOTE_CAST,
            target_type="vote",
            target_id=str(vote.id),
            data=self._audit_refs(vote),
        )
        if config.secret:
            return await self._cast_secret(vote.id, voter_sub, choice)
        return await self._cast_open(vote.id, voter_sub, choice)

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
        vote right any more, so such a vote admits nobody.
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
        means the voter already voted. A ballot never changes after the cast (O11).
        """
        stmt = (
            pg_insert(Ballot)
            .values(vote_id=vote_id, voter_sub=voter_sub, choice=choice)
            .on_conflict_do_nothing(constraint="uq_ballot_vote_voter")
            .returning(Ballot.id)
        )
        inserted = (await self.session.execute(stmt)).first()
        if inserted is None:
            # ON CONFLICT DO NOTHING wrote nothing, so no rollback is needed. The
            # session dependency ``get_session`` ends the transaction on the exception.
            raise ConflictError("Already voted.", code=ALREADY_VOTED)
        await self.session.commit()
        return BallotAccepted(status="cast")

    async def _cast_secret(self, vote_id: UUID, voter_sub: str, choice: str) -> BallotAccepted:
        # `voted_marker` (UNIQUE) is the 'has voted' identity anchor. The code writes
        # the identity-less ballot only when the marker is new. There is no link from
        # choice to voter. A second cast gives 409, as on the open path.
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

        Raises:
            ForbiddenError: The principal cannot view this vote.
        """
        if vote.meeting_id is not None:
            from app.modules.livevote.service import MeetingService

            await MeetingService(self.session).assert_can_read(vote.meeting_id, principal)
            return
        if principal.has("application.read") or principal.has("application.read_all"):
            return
        if self._may_cast(principal, vote.eligible_group):
            return
        gremium_id = await self._vote_gremium_id(
            meeting_id=None, eligible_group=vote.eligible_group
        )
        if gremium_id is not None and await self._manages_in_gremium(gremium_id, principal):
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
        return MyBallot(cast=True, choice=row.choice)

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

    async def _manages_in_gremium(self, gremium_id: UUID, principal: Principal) -> bool:
        """Tell whether a gremium role gives ``vote.manage`` or ``session.manage`` here.

        Both go through ``gremium_ids_for``, so the OAuth scope cap applies (F16).
        """
        from app.modules.admin.gremium_roles import gremium_ids_for

        for perm in ("vote.manage", "session.manage"):
            if gremium_id in await gremium_ids_for(self.session, principal, perm):
                return True
        return False

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
        session manager, the protokollant, or a gremium role with ``vote.manage``.

        The protokollant is an active member of the gremium of the meeting, which
        ``_resolve_protokollant`` enforces, so this reaches no other gremium. The same
        people already create, open and delete the votes of the meeting through
        ``/meetings/{id}/votes``, so the close and the cancel add no right that the
        delete does not already carry.
        """
        # Local imports: `app.modules.livevote.service` imports this module.
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

        1. The admin role (``admin_bypass`` with ``vote.manage``). The OAuth scope cap
           applies, so an admin token with only the ``read`` scope cannot manage.
        2. For a meeting-bound vote, the meeting rule. It keeps the enforced right
           equal to the advertised ``canManageVotes`` flag.
        3. The gremium permission ``vote.manage`` OR ``session.manage`` in the gremium
           of the vote. This covers the application vote that no meeting holds.

        No global permission grants the right. A vote with a free group key resolves
        no gremium, so only the admin role passes.
        """
        from app.modules.admin.gremium_roles import admin_bypass

        if admin_bypass(principal, "vote.manage"):
            return True
        if meeting_id is not None and await self._meeting_grants_vote_management(
            meeting_id, principal
        ):
            return True
        gremium_id = await self._vote_gremium_id(
            meeting_id=meeting_id, eligible_group=eligible_group
        )
        if gremium_id is None:
            return False
        return await self._manages_in_gremium(gremium_id, principal)

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
        """Like ``can_manage_group`` but for an already-loaded vote."""
        return await self.can_manage_group(vote.eligible_group, vote.meeting_id, principal)

    async def assert_can_manage(self, vote: Vote, principal: Principal) -> None:
        """Like ``assert_can_manage_group`` but for an already-loaded vote."""
        await self.assert_can_manage_group(vote.eligible_group, vote.meeting_id, principal)

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
            limit=limit,
            offset=offset,
        )

    async def get(self, vote_id: UUID) -> VoteOut:
        """Return the vote state and the aggregated tally.

        A secret vote exposes only the counts and never the voters. This method has no
        scope gate. It is the internal reuse path, for example the tally broadcast
        after ``cast``. The public read endpoint uses ``get_scoped``.
        """
        vote = await self._get_vote(vote_id)
        config = self._config(vote)
        counts = await self._aggregate(vote, config)
        tally_out = await self._tally_out(vote, config, counts, vote.eligible_count or 0)
        if vote.status == "closed" and vote.result is not None:
            # The column stores text. The values come from tally.result(), a Literal.
            stored_result = cast("tally_mod.VoteResult", vote.result)
            tally_out = tally_out.model_copy(
                update={
                    "result": stored_result,
                    "failed_reason": tally_mod.failed_reason(stored_result, tally_out.quorum_met),
                }
            )
        return self._to_out(vote, config, tally_out)

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
        """Set a loaded vote to ``cancelled`` and audit it, without a commit."""
        previous = vote.status
        vote.status = "cancelled"
        vote.closed_at = now
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
        """Cancel the votes that a state change of the application orphans (F19).

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

        One transaction, one commit (F20). The method stages the tally result,
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

        Raises:
            ConflictError: The vote is not open, or the quorum is not met before the
                window expired.
        """
        # The row lock serializes this call against cast(). No last-second ballot can
        # land between the tally and ``status=closed``.
        vote = await self._get_vote(vote_id, for_update=True)
        if vote.status != "open":
            raise ConflictError(f"vote is {vote.status}, cannot close.", code="conflict")
        config = self._config(vote)
        counts = await self._aggregate(vote, config)
        eligible = vote.eligible_count or 0
        outcome = tally_mod.result(config, counts, eligible)

        # The window expiry counts only when the caller (cron) passes ``now``.
        window_expired = (
            now is not None and vote.closes_at is not None and now >= vote.closes_at
        )

        # Quorum: without a met quorum there is normally no valid result. The close
        # gives 409 instead of a silent 'rejected'. The way out is to collect more
        # ballots or to cancel the vote. Exception: after the cast window expires no
        # more ballots are possible. The vote is then terminal quorum-missed and closes
        # through the ``fail`` branch instead of staying blocked forever.
        if not outcome.quorum_met and not window_expired:
            raise ConflictError(
                "quorum not met — the vote cannot be closed; collect more ballots "
                "or cancel the vote.",
                code="conflict",
            )

        # Expired quorum: force 'rejected' -> fail branch (see ``branch_name``).
        result_value: tally_mod.VoteResult = (
            outcome.result if outcome.quorum_met else "rejected"
        )
        closed_at = now or datetime.now(UTC)

        # #17: fix the attendance of a meeting vote at the close. For a vote with
        # guests the number of eligible voters is the present members plus the admitted
        # guests at this moment: a guest admitted while the vote ran voted too. It is a
        # display value only, because such a vote has no quorum.
        if vote.meeting_id is not None:
            members = await self._present_count(vote)
            guests = await self._guest_attendance(vote, config)
            vote.present_members = members
            vote.present_guests = guests
            if config.guests_vote:
                eligible = members + guests
                vote.eligible_count = eligible

        # Stage the vote state. The commit at the end writes it together with the
        # transition, or alone when the branch is blocked.
        vote.status = "closed"
        vote.result = result_value
        vote.closed_at = closed_at
        await audit_record(
            self.session,
            actor=principal.sub,
            action=AuditAction.VOTE_CLOSE,
            target_type="vote",
            target_id=str(vote.id),
            # Aggregates only, never a voter.
            data={
                **self._audit_refs(vote),
                "result": result_value,
                "counts": dict(counts),
                "quorumMet": outcome.quorum_met,
            },
        )

        # A ``vote`` state has two fixed exits with ``branch`` ``pass`` and ``fail``.
        # ``passed`` fires pass. ``rejected`` and ``tie`` are fail-closed and fire fail.
        # A generic resolution question has no application and fires NO branch. It only
        # holds the result for the protocol.
        branch_name = "pass" if result_value == "passed" else "fail"
        flow = FlowService(self.session, self.dispatcher)
        staged: StagedFire | None = None
        if vote.application_id is not None:
            staged = await self._stage_branch(
                flow,
                vote,
                vote.application_id,
                branch_name,
                principal,
                note=f"vote:{result_value}",
            )
        if staged is not None:
            vote.result_branch_transition_id = staged.transition.id
            # The deadline of the new state joins the same commit.
            await flow.schedule_staged_deadline(staged, commit=False)
        await self.session.commit()

        new_state_id: UUID | None = None
        if staged is not None:
            fired = await flow.after_commit(staged, schedule_deadline=False)
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

    async def _stage_branch(
        self,
        flow: FlowService,
        vote: Vote,
        application_id: UUID,
        branch_name: str,
        principal: Principal,
        *,
        note: str,
    ) -> StagedFire | None:
        """Stage the result branch in a SAVEPOINT, or audit why it is blocked.

        The SAVEPOINT keeps the staged vote close safe: a guard failure, a lost race or
        a missing branch transition rolls back only the branch. The method then writes
        ``vote_branch_blocked`` and returns None.

        Defence in depth: a vote whose Gremium does not decide the current vote state
        of the application (``application.vote_gremium_id``) never fires the branch,
        reason ``vote_gremium_mismatch``. An example is a stale agenda item of a
        meeting of another Gremium.
        """
        reason: str | None = None
        if await self.vote_gremium_mismatch(vote):
            reason = VOTE_GREMIUM_MISMATCH
        else:
            try:
                async with self.session.begin_nested():
                    return await flow.stage_branch(
                        application_id, branch_name, principal, note=note, vote_id=vote.id
                    )
            except ConflictError as exc:
                reason = exc.code
            except NotFoundError:
                # The current state has no such branch: a misconfigured flow, or a
                # vote outside its vote state.
                reason = "no_branch"
        await audit_record(
            self.session,
            actor=principal.sub,
            action=AuditAction.VOTE_BRANCH_BLOCKED,
            target_type="vote",
            target_id=str(vote.id),
            data={**self._audit_refs(vote), "branch": branch_name, "reason": reason},
        )
        return None

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
