"""The close and the cancel of a vote, with the result and the branch of the Antrag."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, select

from app.modules.applications.decision import (
    DecisionIn,
    record_decision,
)
from app.modules.applications.models import Application, ApplicationDecision
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.auth.principal import Principal
from app.modules.flow.models import State, Transition
from app.modules.flow.service import FlowService, StagedFire
from app.modules.voting import circular as circular_mod
from app.modules.voting import election as election_mod
from app.modules.voting import poll as poll_mod
from app.modules.voting import tally as tally_mod
from app.modules.voting.models import Vote
from app.modules.voting.schemas import (
    TallyOut,
    VoteClosed,
    VoteOut,
)
from app.modules.voting.service.access import VoteAccessOps
from app.modules.voting.service.base import (
    VOTE_GREMIUM_MISMATCH,
    _check_closable,
    _orphaned,
)
from app.modules.voting.service.delete import VoteDeleteOps
from app.modules.voting.service.plan import VotePlanOps
from app.modules.voting.webhook_fields import emit_vote_event
from app.shared.config_schemas import VoteConfig
from app.shared.errors import ConflictError, NotFoundError


class VoteCloseOps(VotePlanOps, VoteDeleteOps, VoteAccessOps):
    """The close and the cancel of a vote, with the result and the branch of the Antrag."""

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
            raise ConflictError(f"vote is {vote.status}, cannot cancel.", code="vote_not_open")
        await self._mark_cancelled(vote, now=now or datetime.now(UTC), actor=actor, reason="manual")
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

    async def end_for_plan_version(self, plan_version_id: UUID, *, actor: str | None) -> None:
        """End the votes of a plan version that moves back to draft, without a commit.

        A draft vote is deleted, and an open vote is cancelled, because the plan can
        change again and the Gremium must not decide on the old text. A closed or
        cancelled vote stays as the record of the Gremium. One statement locks the
        votes in id order before the first audit entry, for the reason
        `lock_for_gremium_delete` gives.
        """
        rows = (
            (
                await self.session.execute(
                    select(Vote)
                    .where(
                        Vote.plan_version_id == plan_version_id,
                        Vote.status.in_(("draft", "open")),
                    )
                    .order_by(Vote.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        )
        now = datetime.now(UTC)
        for vote in rows:
            if vote.status == "open":
                await self._mark_cancelled(vote, now=now, actor=actor, reason="plan_to_draft")
        await self.delete_locked_votes(
            [vote for vote in rows if vote.status == "draft"],
            actor=actor or "system",
            reason="plan_to_draft",
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
        state_left = left_state_id is not None and left_state_id != entered_state_id
        unbound_draft = any(v.status == "draft" and v.opens_state_id is None for v in rows)
        left_is_vote = (
            await self._is_vote_state(left_state_id)
            if left_state_id is not None and state_left and unbound_draft
            else False
        )
        cancelled = [
            vote
            for vote in rows
            if _orphaned(vote, left_state_id if state_left else None, left_is_vote=left_is_vote)
        ]
        for vote in cancelled:
            await self._mark_cancelled(vote, now=now, actor=actor, reason="state_left")
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
        A passed vote on a version of a Haushaltsplan passes the step of that version
        in the same commit; a refused vote sends the version back to the draft.
        The audit entry holds aggregates only, never a voter. The status event of a
        fired branch carries the decision for the timeline and the revert.

        Raises:
            ConflictError: The vote is not open, the quorum is not met before the
                window expired, or the window of an Umlaufverfahren is still open
                (``circular_window_open``).
        """
        await self._lock_plan_votes(vote_id)
        vote = await self._get_vote(vote_id, for_update=True)
        if vote.status != "open":
            raise ConflictError(f"vote is {vote.status}, cannot close.", code="vote_not_open")
        if election_mod.is_election(vote):
            return await self._close_election(vote, principal, now=now)
        if poll_mod.is_poll(vote):
            return await self._close_poll(vote, principal, now=now)
        circular_mod.check_manual_close(vote, now, datetime.now(UTC))
        config = self._config(vote)
        counts = await self._aggregate(vote, config)
        outcome = tally_mod.result(
            config,
            counts,
            vote.eligible_count or 0,
            present=await self._quorum_present(vote, config),
        )
        _check_closable(vote, quorum_met=outcome.quorum_met, now=now)

        result_value: tally_mod.VoteResult = outcome.result if outcome.quorum_met else "rejected"
        closed_at = now or datetime.now(UTC)
        eligible = await self._fix_attendance(vote, config)

        plan_version_id: UUID | None = getattr(vote, "plan_version_id", None)
        plans = await self._locked_plan(plan_version_id, principal)
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
        await emit_vote_event(self.session, "vote.closed", vote, counts=counts)

        branch_name = "pass" if result_value == "passed" else "fail"
        flow = FlowService(self.session, self.dispatcher)
        staged, decision = (
            await self._stage_branch(
                flow,
                vote,
                vote.application_id,
                branch_name,
                principal,
                note=f"vote:{result_value}",
                decide=result_value == "passed",
            )
            if vote.application_id is not None
            else (None, None)
        )
        if staged is not None:
            vote.result_branch_transition_id = staged.transition.id
            if decision is not None:
                decision.status_event_id = staged.status_event_id
        if plans is not None and plan_version_id is not None:
            await self.session.flush()
            if result_value == "passed":
                await plans.pass_step_by_vote(plan_version_id, vote.id)
            else:
                await plans.refuse_step_by_vote(plan_version_id, vote.id)
        await self.session.commit()

        new_state_id = (
            (await flow.after_commit(staged)).new_state_id if staged is not None else None
        )

        tally_out = TallyOut(
            counts=counts,
            eligible=eligible,
            voted=sum(counts.values()),
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

    async def _fix_attendance(self, vote: Vote, config: VoteConfig) -> int:
        """Store the attendance of a closing meeting vote and return its eligible count.

        A vote with guests counts the present members plus the admitted guests as
        eligible, because a guest admitted while the vote ran voted too. A vote without
        a meeting keeps its count.
        """
        if vote.meeting_id is not None:
            here = await self._presence(vote)
            members = here.members
            guests = await self._guest_attendance(vote, config)
            vote.present_members = members
            setattr(vote, "present_seats", here.seats)  # noqa: B010
            vote.present_guests = guests
            if config.guests_vote:
                vote.eligible_count = members + guests
        return vote.eligible_count or 0

    async def _record_proposal(
        self, vote: Vote, application_id: UUID, principal: Principal
    ) -> ApplicationDecision | None:
        """Write the proposal of a passed vote as the decision of its application.

        A `pass` branch into an approved state always writes a decision with an amount
        (spec 001611): the amount of the proposal, else the requested amount at the
        close. When the application amount went below the approved amount after the
        vote opened, the decision binds the requested amount and keeps the conditions.
        Any other vote without a proposal writes nothing, and its proposal keeps the
        old rule: an amount above the request binds "as requested" (null).
        """
        proposal = DecisionIn.from_stored(getattr(vote, "proposal", None))
        requested = await self._approval_amount(application_id)
        if proposal is None and requested is None:
            return None
        application = await self._get_application(application_id)
        base = proposal or DecisionIn()
        approved = base.approved_amount
        too_high = approved is not None and (
            application.amount is None or approved > application.amount
        )
        binding = (
            base.model_copy(update={"approved_amount": application.amount})
            if requested is not None and (approved is None or too_high)
            else base.model_copy(update={"approved_amount": None})
            if too_high
            else base
        )
        return await record_decision(
            self.session,
            application,
            binding,
            actor=principal.sub,
            decided_by=None,
            old_approved=application.approved_amount,
            vote_id=vote.id,
        )

    async def _approval_amount(self, application_id: UUID) -> Decimal | None:
        """Return the requested amount when the `pass` branch leads into an approved state.

        None when the branch leads elsewhere, or the application has no amount.
        """
        branch = (
            select(Application.amount)
            .join(
                Transition,
                and_(
                    Transition.flow_version_id == Application.flow_version_id,
                    Transition.from_state_id == Application.current_state_id,
                    Transition.branch == "pass",
                ),
            )
            .join(State, State.id == Transition.to_state_id)
            .where(
                Application.id == application_id,
                State.is_approved.is_(True),
                Application.amount.is_not(None),
            )
            .limit(1)
        )
        return await self.session.scalar(branch)

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
        outcome = await self._election_outcome(
            vote, vote.eligible_count or 0, await self._quorum_present(vote, config)
        )
        _check_closable(vote, quorum_met=outcome.quorum_met, now=now)
        closed_at = now or datetime.now(UTC)
        eligible = await self._fix_attendance(vote, config)
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
        await emit_vote_event(self.session, "vote.closed", vote, counts=outcome.display_counts())
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
        closed_at = now or datetime.now(UTC)
        eligible = await self._fix_attendance(vote, config)
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
        await emit_vote_event(self.session, "vote.closed", vote, counts=outcome.display_counts())
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
        mismatch = await self.vote_gremium_mismatch(vote)
        decision = (
            await self._record_proposal(vote, application_id, principal)
            if decide and not mismatch
            else None
        )
        staged, reason = (
            (None, VOTE_GREMIUM_MISMATCH)
            if mismatch
            else await self._try_stage(
                flow, application_id, branch_name, principal, note=note, vote_id=vote.id
            )
        )
        if staged is None:
            await audit_record(
                self.session,
                actor=principal.sub,
                action=AuditAction.VOTE_BRANCH_BLOCKED,
                target_type="vote",
                target_id=str(vote.id),
                data={**self._audit_refs(vote), "branch": branch_name, "reason": reason},
            )
        return staged, decision

    async def _try_stage(
        self,
        flow: FlowService,
        application_id: UUID,
        branch_name: str,
        principal: Principal,
        *,
        note: str,
        vote_id: UUID,
    ) -> tuple[StagedFire | None, str | None]:
        """Stage the branch in a SAVEPOINT and return it, or no fire and the reason.

        A refused fire gives the code of its conflict (a guard, a lost race), and a
        current state without the branch gives ``no_branch``.
        """
        try:
            async with self.session.begin_nested():
                staged = await flow.stage_branch(
                    application_id, branch_name, principal, note=note, vote_id=vote_id
                )
                return staged, None
        except ConflictError as exc:
            return None, exc.code
        except NotFoundError:
            return None, "no_branch"
