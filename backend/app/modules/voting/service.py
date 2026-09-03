"""Voting service: create -> open -> cast -> close.

Race safety: the DB enforces one ballot per voter.

* open (``secret=false``): ``INSERT ... ON CONFLICT (vote_id, voter_sub)``. With
  ``allowChange`` the statement runs ``DO UPDATE`` for an idempotent update. Without
  it the statement runs ``DO NOTHING`` and returns an empty ``RETURNING`` -> 409
  (double vote).
* secret (``secret=true``): ``voted_marker`` (UNIQUE) records 'has voted'. The ballot
  lands without an identity in ``secret_ballot``. ``allowChange`` has no effect here,
  because nobody can re-link an anonymous ballot. A second cast gives 409.

RBAC is fail-closed. A ``cast`` needs membership in ``vote.eligible_group``. For a
gremium vote that membership IS the ``vote.cast`` right, because only an active gremium
role with ``vote.cast`` writes the namespaced group key. The quorum denominator
(``MeetingService.vote_eligible_count``) reads the same roster, so the counted set and
the admitted set stay equal. Otherwise the call gets 403.
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
            stmt = stmt.with_for_update()
        vote = (await self.session.execute(stmt)).scalar_one_or_none()
        if vote is None:
            raise NotFoundError(f"vote {vote_id} not found")
        return vote

    async def delete(self, vote_id: UUID, *, meeting_id: UUID) -> None:
        """Delete a meeting-bound vote.

        The ballots cascade through the foreign key. The method deletes only a vote of
        this meeting. The caller (router) checks the authorization.

        Raises:
            NotFoundError: The vote does not belong to this meeting.
        """
        vote = await self._get_vote(vote_id)
        if vote.meeting_id != meeting_id:
            raise NotFoundError(f"vote {vote_id} not found in this meeting")
        await self.session.delete(vote)
        await self.session.flush()
        await self.session.commit()

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

        The caller (router) runs the gremium-scoped ``vote.manage`` check, like
        open, close and cancel.

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
        await audit_record(
            self.session,
            actor=actor,
            action=AuditAction.VOTE_DELETE,
            target_type="vote",
            target_id=str(vote_id),
            data={
                "applicationId": str(vote.application_id) if vote.application_id else None,
                "eligibleGroup": vote.eligible_group,
            },
        )
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
        """
        voted = sum(counts.values())
        outcome = tally_mod.result(config, counts, eligible)
        # Query the present denominator only when it changes the reveal decision, that
        # is for an open vote with a meeting. A closed vote or a vote without a meeting
        # needs no query.
        if vote.status == "closed":
            present, revealed = 0, True
        elif config.secret:
            present = await self._present_count(vote)
            revealed = False
        elif vote.meeting_id is None:
            present, revealed = 0, True
        else:
            present = await self._present_count(vote)
            # The expected votes are the present members plus the represented votes of
            # absent delegators. Without them the interim count leaks too early.
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

    async def create(
        self,
        application_id: UUID | None,
        payload: VoteCreate,
        *,
        meeting_id: UUID | None = None,
        agenda_item_id: UUID | None = None,
    ) -> VoteOut:
        """Create a draft vote.

        ``application_id`` is optional. ``None`` marks a generic resolution question of
        a free-text agenda item. Such a vote has no application and fires no flow
        branch on close. ``meeting_id`` binds the vote to a meeting (live vote).
        ``agenda_item_id`` binds it to the agenda item.
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

    async def open(self, vote_id: UUID, *, now: datetime) -> VoteOut:
        """Move the vote from ``draft`` to ``open`` and open the time window.

        The quorum denominator ``eligible_count`` comes from the authoritative roster.
        The create call sets it. It does NOT come from the logged-in users, because
        that would be fail-open. Without it a percent quorum stays fail-closed and
        never counts as met.

        Raises:
            ConflictError: The vote is not in ``draft``.
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
        return await self._cast_open(vote.id, voter_sub, choice, config.allow_change)

    @staticmethod
    def _is_gremium_group(eligible_group: str) -> bool:
        """Tell whether ``eligible_group`` names a gremium, that is a UUID as text."""
        try:
            UUID(eligible_group)
        except (ValueError, TypeError):
            return False
        return True

    @staticmethod
    def _eligible_group_member(principal: Principal, eligible_group: str) -> bool:
        """Check voting eligibility against ``eligible_group``.

        If ``eligible_group`` is a gremium UUID, the cast MUST go through the
        namespaced ``vote:<uuid>`` key. Meeting votes and application votes use such a
        UUID. Only an active ``vote.cast`` membership sets that key. A matching OIDC
        group claim can therefore not satisfy gremium eligibility. A free group key
        (not a UUID) keeps the direct OIDC group check.
        """
        if not VotingService._is_gremium_group(eligible_group):
            return principal.in_group(eligible_group)
        return principal.in_group(vote_group_key(eligible_group))

    @staticmethod
    def _may_cast(principal: Principal, eligible_group: str) -> bool:
        """Tell whether the principal may cast an OWN ballot in this vote.

        For a gremium vote the namespaced key decides on its own. `resolve_principal`
        writes ``vote:<gremium_id>`` for an active membership whose gremium role carries
        ``vote.cast``, and for nothing else, so the key already proves the right. A
        second check on the GLOBAL ``vote.cast`` permission would lock out a member who
        holds the right through the gremium role alone, for example a Sachbearbeitung or
        a Protokoll role. `MeetingService.vote_eligible_count` builds the quorum
        denominator from exactly that roster, so both sides MUST use the same rule.
        Otherwise the vote counts a member who cannot cast, and a percent quorum can
        become unreachable.

        A free group key is a raw OIDC group claim. It proves no membership and feeds no
        server-side roster, so it keeps the global ``vote.cast`` permission next to it.
        """
        if not VotingService._eligible_group_member(principal, eligible_group):
            return False
        return VotingService._is_gremium_group(eligible_group) or principal.has("vote.cast")

    async def _cast_open(
        self, vote_id: UUID, voter_sub: str, choice: str, allow_change: bool
    ) -> BallotAccepted:
        values = {"vote_id": vote_id, "voter_sub": voter_sub, "choice": choice}
        if allow_change:
            # ``xmax = 0`` separates an INSERT (first vote -> "cast") from the ON
            # CONFLICT UPDATE (change -> "changed"). A fresh tuple has a deleting
            # txid of 0.
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
            # ON CONFLICT DO NOTHING wrote nothing, so no rollback is needed. The
            # session dependency ``get_session`` ends the transaction on the exception.
            raise ConflictError("Already voted.", code="conflict")
        await self.session.commit()
        return BallotAccepted(status="cast")

    async def _cast_secret(self, vote_id: UUID, voter_sub: str, choice: str) -> BallotAccepted:
        # `voted_marker` (UNIQUE) is the 'has voted' identity anchor. The code writes
        # the identity-less ballot only when the marker is new. There is no link from
        # choice to voter. allowChange cannot work on an anonymous ballot, so a second
        # cast gives 409.
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

    async def assert_can_read(self, vote: Vote, principal: Principal) -> None:
        """Guard read access to a vote (broken object level authorization).

        A meeting-bound vote follows the meeting visibility rules of
        ``MeetingService.assert_can_read``: member, participant, or delegation
        recipient. A vote without a meeting (application or draft vote) needs a global
        read or manage permission. Without this check any logged-in user could read the
        tally of another gremium through ``GET /api/votes/{id}``, including closed
        SECRET votes.

        The admin role reaches this through `Principal.has` below, not through a
        `principal.roles` read: `has` is where the OAuth scope cap applies.

        Raises:
            ForbiddenError: The principal cannot view this vote.
        """
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

    async def _vote_gremium_id(
        self, *, meeting_id: UUID | None, eligible_group: str
    ) -> UUID | None:
        """Resolve the gremium of a vote.

        A meeting-bound vote inherits the gremium of the meeting. A vote without a
        meeting (application vote) carries the gremium in ``eligible_group`` as the
        gremium UUID in text form. If ``eligible_group`` is a free group key and not a
        UUID, no gremium resolves and the method returns ``None``. Only a global
        ``vote.manage`` or ``admin`` then grants access.
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

    async def assert_can_manage_group(
        self, eligible_group: str, meeting_id: UUID | None, principal: Principal
    ) -> None:
        """Guard the write and lifecycle access to a vote.

        The check is fail-closed and gremium-scoped, symmetric to
        ``assert_can_read``. It covers create, open, close and cancel. Access goes to
        an admin or to a holder of the GLOBAL ``vote.manage`` permission. For a
        meeting-bound vote the meeting rule decides next, which keeps the enforced
        right equal to the advertised ``canManageVotes`` flag. A gremium role with
        ``vote.manage`` for the gremium of the vote also grants access. The last case
        covers the application vote that no meeting holds. It unblocks a legitimate
        per-gremium manager. At the same time it stops an org-wide ``vote.manage``
        holder from opening or closing votes of OTHER gremien without membership. That
        would be a cross-tenant mutation.

        The admin case runs through `principal.has("vote.manage")`, which grants the
        admin role the right AND applies the OAuth scope cap. It used to read
        `principal.roles` directly and return before that check, so a token issued to
        an admin with only the `read` scope could open, close and cancel votes.

        Raises:
            ForbiddenError: The principal cannot manage this vote.
        """
        if principal.has("vote.manage"):
            return
        if meeting_id is not None and await self._meeting_grants_vote_management(
            meeting_id, principal
        ):
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

    async def cancel(self, vote_id: UUID) -> VoteOut:
        """Move the vote from ``open`` to ``cancelled`` without a result or a branch.

        The application stays in the ``vote`` state. An operator can then create a new
        vote or fire a manual exit. This is the only way out when the vote does not
        reach the quorum, because ``close`` is then blocked.

        Raises:
            ConflictError: The vote is not open.
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

    async def close(
        self, vote_id: UUID, principal: Principal, *, now: datetime | None = None
    ) -> VoteClosed:
        """Close an open vote, compute the tally and the result, then fire the branch.

        The close calls ``flow.fire(result_branch)``. It is atomic. The vote change
        (``status=closed`` plus ``result``) and the ``voteResult`` transition commit in
        one transaction. ``fire`` commits the staged vote changes. If ``fire`` fails on
        a guard or a race, the session dependency rolls everything back. The vote then
        stays open and the caller can retry, instead of ending 'closed but branch never
        fired'.

        An expired quorum vote is a special case. Such a vote is time-bound and
        quorum-gated, and its window ``closes_at`` passed with the quorum unmet. It has
        finally failed, because no more ballots are possible. On a manual close
        (``now=None``) the earlier fail-closed 409 applies. If the caller (cron) passes
        ``now`` and the window already expired, the close is different. It marks the
        vote as terminal QUORUM-MISSED and fires the ``fail`` branch. Without that rule
        the application would hang in the ``vote`` state forever. The cron would also
        re-grab the same unclosable vote on each tick.

        Raises:
            ConflictError: The vote is not open, the quorum is not met, or the flow has
                no matching branch transition.
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

        # A ``vote`` state has two fixed exits with ``branch`` ``pass`` and ``fail``.
        # ``passed`` fires pass. ``rejected`` and ``tie`` are fail-closed and fire fail.
        # A generic resolution question has no application and fires NO branch. It only
        # holds the result for the protocol.
        branch_name = "pass" if result_value == "passed" else "fail"
        flow = FlowService(self.session, self.dispatcher)
        branch = (
            await flow.branch_transition(vote.application_id, branch_name)
            if vote.application_id is not None
            else None
        )
        # An application-bound vote WITHOUT a matching branch transition is fail-closed.
        # This happens on a misconfigured flow, or on a vote in a non-``vote`` state.
        # A silent close would fix the result but leave the application in the pre-vote
        # state.
        if vote.application_id is not None and branch is None:
            raise ConflictError(
                f"no '{branch_name}' branch transition for the vote's current state; "
                "flow is misconfigured.",
                code="conflict",
            )

        # Stage the vote state and do NOT commit it here. `fire` writes it atomically
        # with the transition and the status_event. Without a branch the code below
        # commits.
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
