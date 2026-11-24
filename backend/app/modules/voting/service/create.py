"""The create, the change of a draft and the open of a vote."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, cast
from uuid import UUID

from sqlalchemy import select

from app.modules.applications.decision import not_allowed_problem
from app.modules.applications.models import Application
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.auth.principal import Principal
from app.modules.voting import circular as circular_mod
from app.modules.voting import poll as poll_mod
from app.modules.voting.models import Vote
from app.modules.voting.schemas import (
    VoteCreate,
    VoteCreateInternal,
    VoteOut,
)
from app.modules.voting.webhook_fields import emit_vote_event
from app.shared.config_schemas import PollConfig, VoteConfig
from app.shared.errors import ConflictError, ForbiddenError, NotFoundError, ValidationProblem

if TYPE_CHECKING:
    from app.modules.voting.service.service import VotingService

from app.modules.voting.service.access import VoteAccessOps
from app.modules.voting.service.base import (
    _kind_of,
    _vote_config,
    secret_only,
    vote_gremium_mismatch_error,
)
from app.modules.voting.service.plan import VotePlanOps


class VoteCreateOps(VotePlanOps, VoteAccessOps):
    """The create, the change of a draft and the open of a vote."""

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
        with ``vote.cast``). The client cannot send it. The vote is always secret
        (``secret_only``): ``config.secret`` false gives 422. A tie always rejects a
        motion (§F/meetings/voting/000026), so ``tieBreak`` other than ``rejected``
        gives 422.

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
            ValidationProblem: The gremium does not exist (``eligible_group_invalid``),
                is not the gremium of the application (``eligible_group_mismatch``), or
                the body asks for an open vote (``open_vote_unavailable``), or the
                body sets a ``tieBreak`` other than ``rejected``
                (``tie_break_unavailable``) (422).
        """
        from app.modules.auth.policy import admin_bypass

        if payload.config.guests_vote:
            raise ValidationProblem(
                "Only a vote of a public meeting can include guests.",
                code="guests_vote_unavailable",
                errors=[{"field": "config.guestsVote", "msg": "not a public meeting vote"}],
            )
        if payload.config.tie_break != "rejected":
            raise ValidationProblem(
                "A tie always rejects a motion.",
                code="tie_break_unavailable",
                errors=[{"field": "config.tieBreak", "msg": "only rejected is allowed"}],
            )
        sent = payload.config.secret if "secret" in payload.config.model_fields_set else None
        config = payload.config.model_copy(
            update={"secret": secret_only(sent, field="config.secret")}
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
        from app.modules.meetings.rules import MeetingRules

        eligible = await MeetingRules(self.session).vote_eligible_count(gremium_id)
        internal = VoteCreateInternal(
            config=config,
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
        from app.modules.gremien.models import Gremium

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
                    select(State.kind, State.config).where(State.id == application.current_state_id)
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
        vote_id: UUID | None = None,
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
        writes ``poll_created`` for ``actor``. ``vote_id`` presets the id, for a
        caller that stores the id in the same commit.

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
            vote_id=vote_id,
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
        kind = circular_mod.CIRCULAR if payload.circular else _kind_of(payload.config)
        poll = payload.config if isinstance(payload.config, PollConfig) else None
        preset = {"id": vote_id} if vote_id is not None else {}
        vote = Vote(
            **preset,
            kind=kind,
            parent_vote_id=payload.parent_vote_id,
            round=payload.round,
            repeat_of_id=payload.repeat_of_id,
            attempt=payload.attempt,
            application_id=application_id,
            meeting_id=meeting_id,
            agenda_item_id=agenda_item_id,
            eligible_group=str(payload.eligible_group),
            question=payload.question,
            config=(
                payload.config.model_dump(by_alias=True)
                if isinstance(payload.config, VoteConfig)
                else payload.config.model_dump(mode="json", by_alias=True)
            ),
            eligible_count=payload.eligible_count,
            opens_state_id=payload.opens_state_id,
            closes_at=payload.closes_at,
            result_branch_transition_id=payload.result_branch_transition_id,
            proposal=payload.proposal.to_json() if payload.proposal is not None else None,
            plan_version_id=payload.plan_version_id,
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
        config = _vote_config(payload.config)
        empty = dict.fromkeys(config.options, 0)
        return self._to_out(
            vote, config, await self._tally_out(vote, config, empty, vote.eligible_count or 0)
        )

    async def update_draft(
        self,
        vote_id: UUID,
        payload: VoteCreateInternal,
        *,
        meeting_id: UUID,
        actor: str | None = None,
    ) -> Vote:
        """Replace the question, the rules and the options of a prepared meeting vote.

        Only a ``draft`` changes, because a draft holds no ballot: an open vote has
        ballots that were cast against its question, and a closed one is part of the
        record. The kind can change too (a motion becomes a poll on a free-text item).
        The agenda item, the application and the repeat link stay. The open counts the
        roster again, so ``eligible_count`` only keeps the draft consistent. The method
        writes ``vote_update`` and commits.

        Raises:
            NotFoundError: The meeting has no such vote.
            ConflictError: The vote is no longer a draft (``vote_not_editable``).
            ValidationProblem: A proposal without an application
                (``decision_not_allowed``) or with a bad amount (422).
        """
        vote = await self._get_vote(vote_id, for_update=True)
        if vote.meeting_id != meeting_id:
            raise NotFoundError(f"vote {vote_id} not found in this meeting")
        if vote.status != "draft":
            raise ConflictError(
                f"vote is {vote.status}; only a prepared vote can change.",
                code="vote_not_editable",
            )
        if vote.application_id is None and payload.proposal is not None:
            raise not_allowed_problem("Only an application vote takes a decision proposal.")
        if vote.application_id is not None:
            self._check_proposal(await self._get_application(vote.application_id), payload.proposal)
        config = payload.config
        kind = _kind_of(config)
        vote.kind = kind
        vote.question = payload.question
        vote.config = (
            config.model_dump(mode="json", by_alias=True)
            if kind != "motion"
            else config.model_dump(by_alias=True)
        )
        vote.eligible_count = payload.eligible_count
        vote.proposal = payload.proposal.to_json() if payload.proposal is not None else None
        await audit_record(
            self.session,
            actor=actor,
            action=AuditAction.VOTE_UPDATE,
            target_type="vote",
            target_id=str(vote.id),
            data={
                "kind": kind,
                "meetingId": str(meeting_id),
                "agendaItemId": str(vote.agenda_item_id) if vote.agenda_item_id else None,
                "applicationId": str(vote.application_id) if vote.application_id else None,
            },
        )
        await self.session.commit()
        return vote

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
        ``eligible_count``, which replaces the count of the create. A vote without a
        meeting counts the roster of its Gremium again here, so a draft does not keep
        the count of the day it was made (§F/meetings/voting/000939).

        A meeting vote opens only in a ``live`` meeting. The method locks the meeting
        row before the vote row, as the meeting close does.

        A vote on an application in a vote state opens only when its Gremium is the
        Gremium that decides that state (``application.vote_gremium_id``). A draft
        made before the application entered the state, or for another Gremium, gives
        409 ``vote_gremium_mismatch``.

        A poll of a Gremium opens only with its end at least one hour ahead. The audit
        entry records ``guestsVote``, because a vote with guests has no quorum.

        A vote on a version of a Haushaltsplan opens only in a meeting, and only while
        the next step of the version waits for the Gremium of the vote. The step then
        keeps the id of the vote.

        Raises:
            ConflictError: The vote is not in ``draft``, its meeting is not ``live``,
                its Gremium does not decide the vote state of the application, or the
                plan does not wait for it (``plan_step_not_waiting``,
                ``plan_step_vote_runs``).
        """
        meeting_id = await self.session.scalar(select(Vote.meeting_id).where(Vote.id == vote_id))
        if meeting_id is not None:
            await self._lock_live_meeting(meeting_id)
        await self._lock_plan_votes(vote_id)
        vote = await self._get_vote(vote_id, for_update=True)
        if vote.status != "draft":
            raise ConflictError(f"vote is {vote.status}, cannot open.", code="vote_not_draft")
        if await self.vote_gremium_mismatch(vote):
            raise vote_gremium_mismatch_error()
        await poll_mod.PollService(cast("VotingService", self)).check_open(vote, now)
        await circular_mod.CircularService(cast("VotingService", self)).check_open(vote, now)
        await self._take_plan_step(vote, actor)
        config = self._config(vote)
        vote.eligible_count = await self._opening_count(vote, eligible_count)
        vote.opens_at = now
        vote.status = "open"
        data: dict[str, object] = {
            **self._audit_refs(vote),
            "guestsVote": config.guests_vote,
            **({"kind": poll_mod.POLL} if poll_mod.is_poll(vote) else {}),
            **circular_mod.circular_fields(vote),
        }
        await audit_record(
            self.session,
            actor=actor,
            action=AuditAction.VOTE_OPEN,
            target_type="vote",
            target_id=str(vote.id),
            data=data,
        )
        await emit_vote_event(self.session, "vote.opened", vote)
        await self.session.flush()
        await self.session.commit()
        empty = dict.fromkeys(config.options, 0)
        return self._to_out(
            vote, config, await self._tally_out(vote, config, empty, vote.eligible_count or 0)
        )

    async def _opening_count(self, vote: Vote, given: int | None) -> int | None:
        """Return the eligible count of an opening vote.

        The caller of a meeting vote gives the count. A vote without a meeting counts
        its roster now (000939) and keeps the stored count only with a free group key.
        """
        if given is not None or vote.meeting_id is not None:
            return vote.eligible_count if given is None else given
        counted = await self._roster_count(vote)
        return vote.eligible_count if counted is None else counted

    async def _roster_count(self, vote: Vote) -> int | None:
        """Count the eligible members of the Gremium of ``vote`` now.

        An old row with a free group key has no Gremium and gives None.
        """
        from app.modules.meetings.rules import MeetingRules

        try:
            gremium_id = UUID(vote.eligible_group)
        except (ValueError, TypeError):
            return None
        return await MeetingRules(self.session).vote_eligible_count(gremium_id)
