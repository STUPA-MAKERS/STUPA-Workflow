"""The problem codes, the helpers, the constructor, the locks and the shared reads."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.applications.decision import (
    DecisionIn,
    check_approved_amount,
)
from app.modules.applications.models import Application
from app.modules.auth.principal import Principal
from app.modules.flow.dispatch import ActionDispatcher, NullActionDispatcher
from app.modules.meetings.present import (
    NOBODY,
    Present,
    fixed_present,
    present_count,
    quorum_present,
)
from app.modules.voting import circular as circular_mod
from app.modules.voting import election as election_mod
from app.modules.voting import poll as poll_mod
from app.modules.voting import tally as tally_mod
from app.modules.voting.models import SecretBallot, Vote, VotedMarker
from app.modules.voting.schemas import (
    TallyOut,
    VoteKind,
    VoteOut,
)
from app.shared.config_schemas import ElectionConfig, PollConfig, VoteConfig
from app.shared.errors import ConflictError, NotFoundError, ValidationProblem

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


def secret_only(secret: bool | None, *, field: str) -> bool:
    """Return the secrecy of a new vote: always True.

    A decision, an election and a poll are always secret: the platform has no open vote
    (§F/meetings/voting/000024). ``None`` (the client sent no value) gives True. An
    explicit ``false`` gives 422, so a client that asks for an open vote learns that it
    does not get one.

    Raises:
        ValidationProblem: The client asked for an open vote
            (``open_vote_unavailable``, 422).
    """
    if secret is False:
        raise ValidationProblem(
            "A vote is always secret.",
            code="open_vote_unavailable",
            errors=[{"field": field, "msg": "open votes are not available"}],
        )
    return True


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


def _kind_of(config: VoteConfig | ElectionConfig | PollConfig) -> VoteKind:
    """Return the vote kind that a create payload config gives."""
    match config:
        case ElectionConfig():
            return "election"
        case PollConfig():
            return "poll"
        case _:
            return "motion"


def _vote_config(config: VoteConfig | ElectionConfig | PollConfig) -> VoteConfig:
    """Return the motion view of a config: an election and a poll give their projection."""
    match config:
        case ElectionConfig() | PollConfig():
            return config.as_vote_config()
        case _:
            return config


def _with_stored_result(tally_out: TallyOut, vote: Vote) -> TallyOut:
    """Add the stored result of a closed vote and its failed reason to the tally."""
    stored = cast("tally_mod.VoteResult", vote.result)
    return (
        tally_out.model_copy(
            update={
                "result": stored,
                "failed_reason": tally_mod.failed_reason(stored, tally_out.quorum_met),
            }
        )
        if vote.status == "closed" and vote.result is not None
        else tally_out
    )


def _orphaned(vote: Vote, left_state_id: UUID | None, *, left_is_vote: bool) -> bool:
    """Tell whether a state change orphans an open or draft vote of the application.

    An open vote is always orphaned. A draft is orphaned only when it belongs to the
    left state: its ``opens_state_id`` is that state, or it has none and the left state
    is a vote state. ``left_state_id`` is None when the application left no state (or
    came back into the same one), so every draft stays.
    """
    return vote.status != "draft" or _draft_orphaned(
        vote.opens_state_id, left_state_id, left_is_vote=left_is_vote
    )


def _draft_orphaned(
    opens_state_id: UUID | None, left_state_id: UUID | None, *, left_is_vote: bool
) -> bool:
    """Tell whether a draft belongs to the left state (see ``_orphaned``)."""
    match (left_state_id, opens_state_id):
        case (None, _):
            return False
        case (_, None):
            return left_is_vote
        case _:
            return opens_state_id == left_state_id


def _check_closable(vote: Vote, *, quorum_met: bool, now: datetime | None) -> None:
    """Refuse the close of a vote with the quorum missed while its window runs.

    Only the cron close passes ``now``, so only it closes a vote whose window expired
    with the quorum missed (terminal QUORUM-MISSED).

    Raises:
        ConflictError: The quorum is missed and the window has not expired (409).
    """
    window_expired = now is not None and vote.closes_at is not None and now >= vote.closes_at
    if not quorum_met and not window_expired:
        raise ConflictError(
            "The quorum is not met. Cancel the vote, or close it when the quorum is met.",
            code="quorum_not_met",
        )


@dataclass(frozen=True, slots=True)
class _Counted:
    """The counts of a vote for its tally card: per option, turnout, quorum and leader."""

    counts: dict[str, int]
    voted: int
    quorum_met: bool
    leading: str | None


class VotingServiceBase:
    """The problem codes, the helpers, the constructor, the locks and the shared reads."""

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
        base = select(Vote).where(Vote.id == vote_id)
        stmt = (
            base.with_for_update().execution_options(populate_existing=True) if for_update else base
        )
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
        from app.modules.meetings.models import Meeting, MeetingAgendaItem

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

    async def _get_application(
        self, application_id: UUID, *, confirmed_only: bool = False
    ) -> Application:
        """Load the application, or raise 404.

        `confirmed_only=True` also gives 404 for an unconfirmed guest application
        (`email_confirmed_at IS NULL`). Such an application rests in the flow and stays
        invisible, as on the flow routes.
        """
        base = select(Application).where(Application.id == application_id)
        stmt = base.where(Application.email_confirmed_at.is_not(None)) if confirmed_only else base
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
        """Count the votes per option from ``secret_ballot``."""
        return tally_mod.tally(config.options, await self._choices(vote))

    async def _present_count(self, vote: Vote) -> int:
        """Count the present members with a voting right, or 0 without a meeting."""
        return (await self._presence(vote)).members

    async def _presence(self, vote: Vote) -> Present:
        """Return the present count of the meeting of the vote (000946)."""
        if vote.meeting_id is None:
            return NOBODY
        return await present_count(self.session, vote.meeting_id)

    async def _admitted_guest_count(self, vote: Vote) -> int:
        """Count the admitted guests of the meeting of the vote, or 0 without one."""
        if vote.meeting_id is None:
            return 0
        from app.modules.meetings.models import MeetingGuest

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
        present person voted, and the number fixed at the close could be smaller
        than the cast ballots.
        """
        if not config.guests_vote:
            return await self._admitted_guest_count(vote)
        from app.modules.meetings.models import MeetingGuest

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
        voters = set(
            (
                await self.session.execute(
                    select(VotedMarker.voter_sub).where(
                        VotedMarker.vote_id == vote.id,
                        VotedMarker.voter_sub.startswith(GUEST_VOTER_PREFIX),
                    )
                )
            )
            .scalars()
            .all()
        )
        return len(admitted | voters)

    async def _tally_out(
        self, vote: Vote, config: VoteConfig, counts: dict[str, int], eligible: int
    ) -> TallyOut:
        """Build the tally and the turnout progress.

        ``counts`` and ``leading`` are visible only when ``revealed``, and that is the
        case only for a closed vote. Every vote is secret, so a running vote never
        shows an interim tally: only ``voted`` and ``present`` travel. ``voted`` of a
        running vote counts the persons who cast (``voters``), against the present
        persons. After the close it counts the ballots. A person who cast and then left
        stays in the base, so ``present`` of a running vote is never below ``voted``.

        A vote with guests counts the admitted guests as present too: they are
        expected ballots. ``presentMembers`` and ``presentGuests`` give the attendance
        of a meeting vote, live while it runs and fixed after the close.

        An election counts ballots, not votes, and has no leader. A poll only counts: it
        has no quorum and no leader.

        The present count is queried only for a running vote with a meeting, because a
        vote without a meeting has no attendance.
        """
        counted = await self._counted(vote, config, counts, eligible)
        members, guests, present = await self._attendance(vote, config)
        revealed = vote.status == "closed"
        running = vote.status == "open"
        voted = await self.voters(vote.id) if running else counted.voted
        return TallyOut(
            counts=counted.counts if revealed else {},
            eligible=eligible,
            voted=voted,
            present=max(present, voted) if running else present,
            revealed=revealed,
            quorumMet=counted.quorum_met,
            leading=counted.leading if revealed else None,
            result=None,
            presentMembers=members,
            presentGuests=guests,
        )

    async def _counted(
        self, vote: Vote, config: VoteConfig, counts: dict[str, int], eligible: int
    ) -> _Counted:
        """Count a vote by its kind: an election and a poll tally their stored ballots.

        An election counts ballots, not votes, and has no leader. A poll only counts: it
        has no quorum and no leader.
        """
        match getattr(vote, "kind", "motion"):
            case election_mod.ELECTION:
                ev = await self._election_outcome(
                    vote, eligible, await self._quorum_present(vote, config)
                )
                return _Counted(ev.display_counts(), ev.ballots, ev.quorum_met, None)
            case poll_mod.POLL:
                pv = await self._poll_outcome(vote)
                return _Counted(pv.display_counts(), pv.ballots, True, None)
            case _:
                outcome = tally_mod.result(
                    config, counts, eligible, present=await self._quorum_present(vote, config)
                )
                return _Counted(counts, sum(counts.values()), outcome.quorum_met, outcome.leading)

    async def _attendance(
        self, vote: Vote, config: VoteConfig
    ) -> tuple[int | None, int | None, int]:
        """Return the present members, the present guests and the present count.

        A closed vote gives the values fixed at the close and a present count of 0. A
        running vote with a meeting queries them, and a vote with guests counts the
        guests as present. A vote without a meeting has no attendance.
        """
        match (vote.status == "closed", vote.meeting_id is not None):
            case (True, _):
                return (
                    getattr(vote, "present_members", None),
                    getattr(vote, "present_guests", None),
                    0,
                )
            case (False, True):
                here = await self._presence(vote)
                guests = await self._guest_attendance(vote, config)
                return (
                    here.members,
                    guests,
                    here.total + guests if config.guests_vote else here.total,
                )
            case _:
                return None, None, 0

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
            proposal=DecisionIn.from_stored(getattr(vote, "proposal", None)),
            repeatOfId=getattr(vote, "repeat_of_id", None),
            attempt=getattr(vote, "attempt", 1) or 1,
            planVersionId=getattr(vote, "plan_version_id", None),
            cancelReason=getattr(vote, "cancel_reason", None),
            **circular_mod.circular_fields(vote),
            **election_mod.election_fields(vote),
            **poll_mod.poll_fields(vote),
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

    async def _choices(self, vote: Vote) -> Sequence[str]:
        """Load the stored choices of a vote from ``secret_ballot``."""
        return (
            (
                await self.session.execute(
                    select(SecretBallot.choice).where(SecretBallot.vote_id == vote.id)
                )
            )
            .scalars()
            .all()
        )

    async def _election_outcome(
        self, vote: Vote, eligible: int, present: int | None = None
    ) -> tally_mod.ElectionOutcome:
        """Tally an election from its stored ballots."""
        config = election_mod.election_config(vote)
        choices = await self._choices(vote)
        return election_mod.outcome_of(
            config, choices, eligible, getattr(vote, "round", 1) or 1, present
        )

    async def _quorum_present(self, vote: Vote, config: VoteConfig) -> int | None:
        """Return the present count that the quorum of a meeting vote compares.

        Only a meeting vote with ``quorumBasis = present`` has one: the persons with the
        attendance status ``present`` plus the pool substitutes on a seat. A member who
        gave a delegation is not present, so the ballot of a delegation does not count.
        A closed vote takes the members and the seats fixed at its close.
        """
        if vote.meeting_id is None or config.quorum_basis != "present":
            return None
        fixed = fixed_present(vote)
        here = await self._presence(vote) if None in fixed else NOBODY
        return quorum_present(fixed, here)

    async def _poll_outcome(self, vote: Vote) -> tally_mod.PollOutcome:
        """Tally a poll from its stored ballots."""
        config = poll_mod.poll_config(vote)
        choices = await self._choices(vote)
        return tally_mod.tally_poll(choices, config)

    async def voters(self, vote_id: UUID) -> int:
        """Return the number of persons who cast in the vote (§F/meetings/voting/000933).

        One cast counts once, for however many voting rights it writes a ballot.
        """
        count = await self.session.scalar(
            select(func.count())
            .select_from(VotedMarker)
            .where(VotedMarker.vote_id == vote_id, VotedMarker.same_caster.is_(False))
        )
        return int(count or 0)
