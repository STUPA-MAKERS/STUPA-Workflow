"""Voting service: create -> open -> cast -> close.

Race safety - one ballot per voter is enforced in the DB:
* open (``secret=false``): ``INSERT ... ON CONFLICT (vote_id, voter_sub)`` -
  ``allowChange`` -> ``DO UPDATE`` (idempotent update), else ``DO NOTHING`` and an
  empty ``RETURNING`` -> 409 (double vote).
* secret (``secret=true``): ``voted_marker`` (UNIQUE) records 'has voted'; the
  ballot lands identity-less in ``secret_ballot``. ``allowChange`` has no effect
  here (anonymous ballot cannot be re-linked) -> a second cast -> 409.

RBAC fail-closed: ``cast`` requires membership in ``vote.eligible_group`` (on top
of the ``vote.cast`` permission in the router); otherwise 403.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import func, literal_column, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.applications.models import Application
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.auth.principal import Principal
from app.modules.auth.rbac import vote_group_key
from app.modules.delegations.service import voting_delegation_check
from app.modules.flow.dispatch import ActionDispatcher, NullActionDispatcher
from app.modules.flow.service import FlowService
from app.modules.voting import tally as tally_mod
from app.modules.voting.models import Ballot, SecretBallot, Vote, VotedMarker
from app.modules.voting.schemas import (
    BallotAccepted,
    TallyOut,
    VoteClosed,
    VoteCreate,
    VoteOut,
)
from app.shared.config_schemas import VoteConfig
from app.shared.errors import ConflictError, ForbiddenError, NotFoundError, ValidationProblem


def open_tally_revealed(present: int, voted: int, expected: int) -> bool:
    """Reveal rule for open, non-secret votes.

    The running count only becomes visible once all expected ballots are in - otherwise
    the interim tally leaks on the beamer/voter. ``expected`` is the denominator: present
    members plus active vote delegations whose delegator is ABSENT (the delegate casts a
    represented ballot that ``voted`` counts). Without that add-on ``voted`` could exceed
    ``present`` before all present members voted and reveal the tally early. Shared with
    the live-vote reload path.
    """
    return present > 0 and voted >= expected


class VotingService:
    """Service bound to an ``AsyncSession`` (+ optional flow dispatcher)."""

    def __init__(self, session: AsyncSession, dispatcher: ActionDispatcher | None = None) -> None:
        self.session = session
        self.dispatcher: ActionDispatcher = dispatcher or NullActionDispatcher()

    # --- helpers ---
    async def _get_vote(self, vote_id: UUID, *, for_update: bool = False) -> Vote:
        """Load a vote; ``for_update`` locks the row (cast/close serialization).

        Without the lock a last-second ballot could commit between tally and
        ``status=closed`` and be missing from the recorded result.
        """
        stmt = select(Vote).where(Vote.id == vote_id)
        if for_update:
            stmt = stmt.with_for_update()
        vote = (await self.session.execute(stmt)).scalar_one_or_none()
        if vote is None:
            raise NotFoundError(f"vote {vote_id} not found")
        return vote

    async def delete(self, vote_id: UUID, *, meeting_id: UUID) -> None:
        """Delete a meeting-bound vote (ballots cascade via FK).

        Only votes of this meeting; the caller (router) checks authorization.
        """
        vote = await self._get_vote(vote_id)
        if vote.meeting_id != meeting_id:
            raise NotFoundError(f"vote {vote_id} not found in this meeting")
        await self.session.delete(vote)
        await self.session.flush()
        await self.session.commit()

    async def _get_application(self, application_id: UUID) -> Application:
        app = (
            await self.session.execute(select(Application).where(Application.id == application_id))
        ).scalar_one_or_none()
        if app is None:
            raise NotFoundError(f"application {application_id} not found")
        return app

    @staticmethod
    def _config(vote: Vote) -> VoteConfig:
        return VoteConfig.model_validate(vote.config)

    async def _aggregate(self, vote: Vote, config: VoteConfig) -> dict[str, int]:
        """Count votes per option - open from ``ballot``, secret from ``secret_ballot``."""
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
        """Count of present meeting members (reveal denominator). 0 without a meeting."""
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

    async def _absent_delegated_count(self, vote: Vote) -> int:
        """Active vote delegations in this meeting/gremium whose delegator is NOT present.

        The delegate casts a represented ballot that ``voted`` counts even though the
        delegator is not among the present, so this add-on to the reveal denominator keeps
        ``voted`` from exceeding ``present`` and revealing the tally early. ``eligible_group``
        is the gremium UUID as text; if it does not parse there is no delegation (0).
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
        """Tally + turnout progress. ``counts``/``leading`` are only visible when
        ``revealed``: closed, or (not secret and all present have voted). Session-less
        open non-secret votes stay visible (no 'present' notion). When hidden, only
        ``voted``/``present`` travel."""
        voted = sum(counts.values())
        outcome = tally_mod.result(config, counts, eligible)
        # Only query the present denominator when it affects the reveal decision
        # (open vote with a meeting). Closed/session-less needs no query.
        if vote.status == "closed":
            present, revealed = 0, True
        elif config.secret:
            present = await self._present_count(vote)
            revealed = False
        elif vote.meeting_id is None:
            present, revealed = 0, True
        else:
            present = await self._present_count(vote)
            # Expected votes = present + represented votes of absent delegators
            # (else the interim count leaks too early).
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
            tally=tally_out,
        )

    # --- create ---
    async def create(
        self,
        application_id: UUID | None,
        payload: VoteCreate,
        *,
        meeting_id: UUID | None = None,
        agenda_item_id: UUID | None = None,
    ) -> VoteOut:
        """Create a draft vote.

        ``application_id`` is optional: ``None`` = generic resolution question of a
        free-text TOP (no application, no flow branch on close). ``meeting_id`` binds
        the vote to a meeting (live vote); ``agenda_item_id`` to the TOP.
        """
        if application_id is not None:
            await self._get_application(application_id)
        vote = Vote(
            application_id=application_id,
            meeting_id=meeting_id,
            agenda_item_id=agenda_item_id,
            eligible_group=payload.eligible_group,
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

    # --- open ---
    async def open(self, vote_id: UUID, *, now: datetime) -> VoteOut:
        """``draft`` -> ``open``: open the time window.

        The quorum denominator (``eligible_count``) comes from the authoritative roster
        and is set at creation - NOT derived from logged-in users (that would be
        fail-open). If missing, a percent quorum stays fail-closed and unmet.
        """
        vote = await self._get_vote(vote_id)
        if vote.status != "draft":
            raise ConflictError(f"vote is {vote.status}, cannot open.", code="conflict")
        config = self._config(vote)
        vote.opens_at = now
        vote.status = "open"
        await self.session.flush()
        await self.session.commit()
        empty = {opt: 0 for opt in config.options}
        return self._to_out(
            vote, config, await self._tally_out(vote, config, empty, vote.eligible_count or 0)
        )

    # --- cast ---
    async def cast(
        self,
        vote_id: UUID,
        principal: Principal,
        choice: str,
        *,
        now: datetime,
        as_delegation: bool = False,
    ) -> BallotAccepted:
        """Cast a vote. 409 (closed/double), 403 (not eligible), 422 (unknown option).

        ``as_delegation=True`` casts the REPRESENTED vote: it runs under the delegator's
        ``sub`` - own vote and represented vote are two separate ballots (a transfer, not
        a duplicate; the per-(vote, voter) unique constraint protects each individually).
        """
        # Row lock serializes against close(): status check and ballot insert share a
        # transaction - no ballot lands after the tally.
        vote = await self._get_vote(vote_id, for_update=True)
        if vote.status != "open":
            raise ConflictError("vote is not open.", code="conflict")
        if vote.closes_at is not None and now >= vote.closes_at:
            raise ConflictError("voting window has closed.", code="conflict")
        # `blocked` = the caller delegated their voting right for THIS meeting.
        # `delegator_sub` = a voting right was transferred to them (None = none).
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
            # Own vote: global ``vote.cast`` + group membership (the router gates auth
            # only, so external substitutes get through).
            if not principal.has("vote.cast") or not self._eligible_group_member(
                principal, vote.eligible_group
            ):
                raise ForbiddenError("Not eligible to vote in this ballot.")
            voter_sub = principal.sub
        config = self._config(vote)
        if choice not in config.options:
            raise ValidationProblem(
                "Unknown vote option.",
                errors=[{"field": "choice", "msg": "not in vote options"}],
            )
        if as_delegation:
            # Audit the delegation USE; on a later 409 (double) the session dependency
            # rolls back the transaction including this entry.
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
        return await self._cast_open(vote.id, voter_sub, choice, config.allow_change)

    @staticmethod
    def _eligible_group_member(principal: Principal, eligible_group: str) -> bool:
        """Check voting eligibility against ``eligible_group``.

        If ``eligible_group`` is a gremium UUID (meeting/application votes), the cast MUST
        go through the namespaced ``vote:<uuid>`` key that only an active ``vote.cast``
        membership sets - so a matching OIDC group claim cannot falsely satisfy gremium
        eligibility. Free (non-UUID) group keys keep the direct OIDC group check.
        """
        try:
            UUID(eligible_group)
        except (ValueError, TypeError):
            return principal.in_group(eligible_group)
        return principal.in_group(vote_group_key(eligible_group))

    async def _cast_open(
        self, vote_id: UUID, voter_sub: str, choice: str, allow_change: bool
    ) -> BallotAccepted:
        values = {"vote_id": vote_id, "voter_sub": voter_sub, "choice": choice}
        if allow_change:
            # ``xmax = 0`` distinguishes an INSERT (first vote -> "cast") from the ON
            # CONFLICT UPDATE (change -> "changed"): a freshly inserted tuple has
            # deleting txid 0.
            stmt = (
                pg_insert(Ballot)
                .values(**values)
                .on_conflict_do_update(
                    constraint="uq_ballot_vote_voter",
                    set_={"choice": choice, "at": func.now()},
                )
                .returning(literal_column("(xmax = 0)").label("inserted"))
            )
            row = (await self.session.execute(stmt)).first()
            await self.session.commit()
            inserted = bool(row.inserted) if row is not None else False
            return BallotAccepted(status="cast" if inserted else "changed")

        stmt = (
            pg_insert(Ballot)
            .values(**values)
            .on_conflict_do_nothing(constraint="uq_ballot_vote_voter")
            .returning(Ballot.id)
        )
        inserted = (await self.session.execute(stmt)).first()
        if inserted is None:
            # ON CONFLICT DO NOTHING wrote nothing -> no rollback needed; the session
            # dependency (get_session) ends the transaction on the exception.
            raise ConflictError("Already voted.", code="conflict")
        await self.session.commit()
        return BallotAccepted(status="cast")

    async def _cast_secret(self, vote_id: UUID, voter_sub: str, choice: str) -> BallotAccepted:
        # `voted_marker` (UNIQUE) is the 'has voted' identity anchor. Only when it
        # is new is the identity-less ballot written (no choice<->voter link;
        # allowChange is impossible anonymously -> 409).
        marker = (
            pg_insert(VotedMarker)
            .values(vote_id=vote_id, voter_sub=voter_sub)
            .on_conflict_do_nothing(constraint="uq_voted_marker_vote_voter")
            .returning(VotedMarker.id)
        )
        inserted = (await self.session.execute(marker)).first()
        if inserted is None:
            raise ConflictError("Already voted.", code="conflict")
        self.session.add(SecretBallot(vote_id=vote_id, choice=choice))
        await self.session.commit()
        return BallotAccepted(status="cast")

    # --- get ---
    async def assert_can_read(self, vote: Vote, principal: Principal) -> None:
        """Guard read access to a vote (broken-object-level authorization).

        Meeting-bound votes follow meeting visibility (member/participant/delegation
        recipient) like ``MeetingService.assert_can_read``; session-less
        (application/draft) votes require a global read/manage permission. Without this
        check any logged-in user could read another gremium's tally via
        ``GET /api/votes/{id}`` - including closed SECRET votes.
        """
        if "admin" in principal.roles:
            return
        if vote.meeting_id is not None:
            from app.modules.livevote.service import MeetingService

            await MeetingService(self.session).assert_can_read(vote.meeting_id, principal)
            return
        if (
            principal.has("vote.manage")
            or principal.has("application.read")
            or principal.has("application.read_all")
        ):
            return
        raise ForbiddenError("not allowed to view this vote")

    async def get_scoped(self, vote_id: UUID, principal: Principal) -> VoteOut:
        """Like ``get`` but fail-closed scoped to the vote's read audience."""
        vote = await self._get_vote(vote_id)
        await self.assert_can_read(vote, principal)
        return await self.get(vote_id)

    # --- manage-scope ---
    async def _vote_gremium_id(
        self, *, meeting_id: UUID | None, eligible_group: str
    ) -> UUID | None:
        """Resolve a vote's gremium.

        Meeting-bound votes inherit the meeting's gremium; session-less (application)
        votes carry the gremium as ``eligible_group`` (gremium UUID as text). If
        ``eligible_group`` is a free group key (not a UUID) there is no resolvable
        gremium -> ``None`` (then only global ``vote.manage`` / ``admin`` grants access).
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

    async def assert_can_manage_group(
        self, eligible_group: str, meeting_id: UUID | None, principal: Principal
    ) -> None:
        """Fail-closed gremium-scope write/lifecycle access (create/open/close/cancel),
        symmetric to ``assert_can_read``.

        Allowed for admin, holders of the GLOBAL ``vote.manage`` permission, or a gremium
        role with ``vote.manage`` for the vote's gremium (like
        ``MeetingService.can_manage_votes``). The latter unblocks legitimate per-gremium
        managers while stopping an org-wide ``vote.manage`` holder from opening/closing
        votes of OTHER gremien without membership (cross-tenant mutation).
        """
        if "admin" in principal.roles:
            return
        if principal.has("vote.manage"):
            return
        gremium_id = await self._vote_gremium_id(
            meeting_id=meeting_id, eligible_group=eligible_group
        )
        if gremium_id is not None:
            from app.modules.admin.gremium_roles import gremium_ids_with_permission

            if gremium_id in await gremium_ids_with_permission(
                self.session, principal.sub, "vote.manage"
            ):
                return
        raise ForbiddenError("not allowed to manage this vote")

    async def assert_can_manage(self, vote: Vote, principal: Principal) -> None:
        """Like ``assert_can_manage_group`` but for an already-loaded vote."""
        await self.assert_can_manage_group(vote.eligible_group, vote.meeting_id, principal)

    async def assert_can_manage_vote(self, vote_id: UUID, principal: Principal) -> None:
        """Load the vote (404 if missing) and check ``assert_can_manage``.

        Used by the ``/votes/{id}/{open,close,cancel}`` router before the lifecycle call
        so open/close/cancel are fail-closed gremium-scoped like ``get_scoped``. The
        internal live-vote/cron path calls the lifecycle methods directly (own gate) and
        deliberately bypasses this check.
        """
        vote = await self._get_vote(vote_id)
        await self.assert_can_manage(vote, principal)

    async def get(self, vote_id: UUID) -> VoteOut:
        """Vote state + aggregated tally (secret: only counts, never voters).

        No scope gate - internal reuse path (e.g. tally broadcast after ``cast``); the
        public read endpoint uses ``get_scoped``.
        """
        vote = await self._get_vote(vote_id)
        config = self._config(vote)
        counts = await self._aggregate(vote, config)
        tally_out = await self._tally_out(vote, config, counts, vote.eligible_count or 0)
        if vote.status == "closed" and vote.result is not None:
            # Persisted as a text column; values come from tally.result() -> Literal.
            stored_result = cast("tally_mod.VoteResult", vote.result)
            tally_out = tally_out.model_copy(
                update={
                    "result": stored_result,
                    "failed_reason": tally_mod.failed_reason(stored_result, tally_out.quorum_met),
                }
            )
        return self._to_out(vote, config, tally_out)

    # --- cancel ---
    async def cancel(self, vote_id: UUID) -> VoteOut:
        """``open`` -> ``cancelled``: abort without a result and without a branch.

        The application stays in the ``vote`` state - a new vote can be created or a
        manual exit fired. The only way out when the quorum is not reached (``close`` is
        then blocked).
        """
        vote = await self._get_vote(vote_id, for_update=True)
        if vote.status != "open":
            raise ConflictError(f"vote is {vote.status}, cannot cancel.", code="conflict")
        vote.status = "cancelled"
        await self.session.commit()
        config = self._config(vote)
        counts = await self._aggregate(vote, config)
        return self._to_out(
            vote,
            config,
            await self._tally_out(vote, config, counts, vote.eligible_count or 0),
        )

    # --- close ---
    async def close(
        self, vote_id: UUID, principal: Principal, *, now: datetime | None = None
    ) -> VoteClosed:
        """``open`` -> ``closed``: tally -> result -> ``flow.fire(result_branch)``.

        Atomic: closing the vote (``status=closed`` + ``result``) and the ``voteResult``
        transition commit in one transaction (``fire`` commits the staged vote changes).
        If ``fire`` fails (guard/race), the session dependency rolls everything back,
        leaving the vote open and retryable instead of 'closed but branch never fired'.

        Expired quorum vote: a time-bound, quorum-gated vote whose window (``closes_at``)
        has passed with the quorum unmet has finally failed - no more ballots are
        possible. On a manual close (``now=None``) the earlier fail-closed 409 applies. If
        the caller (cron) passes ``now`` and the window has already expired, the vote is
        closed as terminal QUORUM-MISSED and the ``fail`` branch fires - otherwise the
        application would hang in the ``vote`` state forever and the cron would re-grab the
        same unclosable vote each tick.
        """
        # Row lock serializes against cast(): no last-second ballot between tally and
        # ``status=closed``.
        vote = await self._get_vote(vote_id, for_update=True)
        if vote.status != "open":
            raise ConflictError(f"vote is {vote.status}, cannot close.", code="conflict")
        config = self._config(vote)
        counts = await self._aggregate(vote, config)
        eligible = vote.eligible_count or 0
        outcome = tally_mod.result(config, counts, eligible)

        # Window expired? Only relevant when the caller passes ``now`` (cron).
        window_expired = (
            now is not None and vote.closes_at is not None and now >= vote.closes_at
        )

        # Quorum: without a met quorum there is normally no valid result - closing is
        # blocked (409) instead of silently ending as 'rejected'. Escape: collect more
        # ballots or cancel the vote. Exception: if the cast window has already expired,
        # no more ballots are possible -> the vote is terminal quorum-missed and closes
        # via the ``fail`` branch (instead of being blocked forever).
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

        # A ``vote`` state has two fixed exits with ``branch`` ``pass``/``fail``.
        # ``passed`` -> pass, otherwise (``rejected``/``tie``) fail-closed -> fail.
        # Generic resolution questions (no application) fire NO branch - they only hold
        # the result for the protocol.
        branch_name = "pass" if result_value == "passed" else "fail"
        flow = FlowService(self.session, self.dispatcher)
        branch = (
            await flow.branch_transition(vote.application_id, branch_name)
            if vote.application_id is not None
            else None
        )
        # Application-bound vote WITHOUT a matching branch transition (misconfigured flow
        # / vote on a non-``vote`` state): fail-closed instead of closing silently, else
        # the result would be fixed but the application would stay in the pre-vote state.
        if vote.application_id is not None and branch is None:
            raise ConflictError(
                f"no '{branch_name}' branch transition for the vote's current state; "
                "flow is misconfigured.",
                code="conflict",
            )

        # Stage the vote state - do NOT commit separately: `fire` writes it atomically
        # with the transition + status_event; without a branch we commit here.
        vote.status = "closed"
        vote.result = result_value
        vote.result_branch_transition_id = branch.id if branch is not None else None

        new_state_id: UUID | None = None
        if branch is not None and vote.application_id is not None:
            fired = await flow.fire_branch(
                vote.application_id, branch_name, principal, note=f"vote:{result_value}"
            )
            new_state_id = fired.new_state_id
        else:
            await self.session.commit()

        tally_out = TallyOut(
            counts=counts,
            eligible=eligible,
            quorumMet=outcome.quorum_met,
            leading=outcome.leading,
            result=result_value,
            failedReason=tally_mod.failed_reason(result_value, outcome.quorum_met),
        )
        return VoteClosed(
            id=vote.id,
            meetingId=vote.meeting_id,
            result=result_value,
            tally=tally_out,
            firedTransitionId=branch.id if branch is not None else None,
            newStateId=new_state_id,
        )
