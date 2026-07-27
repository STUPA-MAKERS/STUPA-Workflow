"""Meeting-bound vote reads: tally reload, reveal rule, and quorum helpers."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select

from app.modules.admin.gremium_roles import _time_valid_clause
from app.modules.admin.models import Gremium, GremiumMembership, GremiumRole
from app.modules.delegations.models import MeetingDelegation
from app.modules.livevote.models import MeetingAttendance
from app.modules.livevote.schemas import MeetingVoteOut
from app.modules.livevote.service.service_base import MeetingServiceBase
from app.modules.voting.models import Vote
from app.modules.voting.service import open_tally_revealed
from app.shared.config_schemas import VoteConfig


class VoteReadOps(MeetingServiceBase):
    """Reload-path vote aggregation and vote-related lookup helpers."""

    async def _votes_for(self, meeting_ids: list[UUID]) -> dict[UUID, list[MeetingVoteOut]]:
        """Return the votes bound to the meetings, grouped per `meeting_id`."""
        if not meeting_ids:
            return {}
        rows = (
            (
                await self.session.execute(
                    select(Vote).where(Vote.meeting_id.in_(meeting_ids)).order_by(Vote.created_at)
                )
            )
            .scalars()
            .all()
        )
        # Rebuild the counts, the leading option, and the failed reason per vote from
        # the ballots. This is the reload path. The live WebSocket path already carries
        # these values. One batched query keeps this free of N+1.
        tallies = await self._vote_tallies(rows)
        present_by_meeting = await self._present_by_meeting(meeting_ids)
        # The substitute ballots of absent delegators per meeting and gremium top up
        # the reveal denominator. The voting service applies the same rule in
        # `open_tally_revealed`, so the two paths cannot drift. The query runs only
        # when an open, non-secret vote exists. Only then does the denominator feed a
        # reveal decision. A closed or secret vote never reveals through it.
        needs_deleg = any(
            v.meeting_id is not None
            and v.status not in ("closed", "cancelled")
            and not bool((v.config if isinstance(v.config, dict) else {}).get("secret"))
            for v in rows
        )
        absent_deleg = (
            await self._absent_delegated_by_meeting(meeting_ids) if needs_deleg else {}
        )
        out: dict[UUID, list[MeetingVoteOut]] = {}
        for v in rows:
            if v.meeting_id is None:
                continue
            cfg = v.config if isinstance(v.config, dict) else {}
            opts = cfg.get("options") or []
            secret = bool(cfg.get("secret"))
            counts, leading, reason = tallies.get(v.id, (None, None, None))
            voted = sum((counts or {}).values())
            present = present_by_meeting.get(v.meeting_id, 0)
            # The reveal rule matches the voting service. A closed vote reveals. A
            # non-secret vote reveals when all expected ballots are in. The expected
            # ballots are the present members plus the substitutes of absent
            # delegators. In every other case, hide the counts and the leading option
            # to prevent an interim leak.
            if v.status == "closed":
                revealed = True
            elif secret:
                revealed = False
            else:
                expected = present + absent_deleg.get((v.meeting_id, v.eligible_group), 0)
                revealed = open_tally_revealed(present, voted, expected)
            out.setdefault(v.meeting_id, []).append(
                MeetingVoteOut(
                    id=v.id,
                    applicationId=v.application_id,
                    agendaItemId=v.agenda_item_id,
                    question=v.question,
                    options=list(opts),
                    status=v.status,  # type: ignore[arg-type]
                    result=v.result,
                    counts=counts if revealed else {},
                    leading=leading if revealed else None,
                    voted=voted,
                    present=present,
                    revealed=revealed,
                    failedReason=reason,
                )
            )
        return out

    async def _present_by_meeting(self, meeting_ids: list[UUID]) -> dict[UUID, int]:
        """Return `{meeting_id: number of present members}`, the reveal denominator."""
        if not meeting_ids:
            return {}
        rows = (
            await self.session.execute(
                select(MeetingAttendance.meeting_id, func.count())
                .where(
                    MeetingAttendance.meeting_id.in_(meeting_ids),
                    MeetingAttendance.status == "present",
                )
                .group_by(MeetingAttendance.meeting_id)
            )
        ).all()
        return {mid: n for mid, n in rows}

    async def _absent_delegated_by_meeting(
        self, meeting_ids: list[UUID]
    ) -> dict[tuple[UUID, str], int]:
        """Count the active voting delegations whose delegator is absent.

        The result maps `(meeting_id, str(gremium_id))` to the count and tops up the
        reveal denominator. The key matches `vote.eligible_group`, which holds the
        gremium UUID as text. Each such delegation yields one substitute ballot that
        counts into `voted`. The delegation therefore raises the expected
        denominator. One batched query keeps this free of N+1.
        """
        if not meeting_ids:
            return {}
        present_subq = (
            select(MeetingAttendance.principal_id)
            .where(
                MeetingAttendance.meeting_id == MeetingDelegation.meeting_id,
                MeetingAttendance.status == "present",
                MeetingAttendance.principal_id == MeetingDelegation.delegator_principal_id,
            )
            .exists()
        )
        rows = (
            await self.session.execute(
                select(
                    MeetingDelegation.meeting_id,
                    MeetingDelegation.gremium_id,
                    func.count(),
                )
                .where(
                    MeetingDelegation.meeting_id.in_(meeting_ids),
                    MeetingDelegation.delegate_voting.is_(True),
                    ~present_subq,
                )
                .group_by(MeetingDelegation.meeting_id, MeetingDelegation.gremium_id)
            )
        ).all()
        return {(mid, str(gid)): n for mid, gid, n in rows}

    async def _vote_tallies(
        self, votes: Sequence[Vote]
    ) -> dict[
        UUID,
        tuple[dict[str, int] | None, str | None, Literal["quorum", "majority"] | None],
    ]:
        """Build `{vote_id: (counts, leading, failedReason)}` from the ballots.

        This is the reload path. The method loads the ballots in one batch. An open
        vote reads `ballot`. A secret vote reads `secret_ballot`. The method then
        applies the pure tally logic. It sets `failedReason` for closed, failed votes
        only.
        """
        from app.modules.voting import tally as tally_mod
        from app.modules.voting.models import Ballot, SecretBallot

        if not votes:
            return {}
        ids = [v.id for v in votes]
        open_rows = (
            await self.session.execute(
                select(Ballot.vote_id, Ballot.choice).where(Ballot.vote_id.in_(ids))
            )
        ).all()
        secret_rows = (
            await self.session.execute(
                select(SecretBallot.vote_id, SecretBallot.choice).where(
                    SecretBallot.vote_id.in_(ids)
                )
            )
        ).all()
        open_by_vote: dict[UUID, list[str | None]] = {}
        for vid, choice in open_rows:
            open_by_vote.setdefault(vid, []).append(choice)
        secret_by_vote: dict[UUID, list[str | None]] = {}
        for vid, choice in secret_rows:
            secret_by_vote.setdefault(vid, []).append(choice)

        out: dict[
            UUID,
            tuple[dict[str, int] | None, str | None, Literal["quorum", "majority"] | None],
        ] = {}
        for v in votes:
            config = VoteConfig.model_validate(v.config)
            choices = secret_by_vote.get(v.id, []) if config.secret else open_by_vote.get(v.id, [])
            counts = tally_mod.tally(config.options, choices)
            outcome = tally_mod.result(config, counts, v.eligible_count or 0)
            reason: Literal["quorum", "majority"] | None = None
            if v.status == "closed" and v.result is not None:
                reason = tally_mod.failed_reason(outcome.result, outcome.quorum_met)
            out[v.id] = (dict(counts), outcome.leading, reason)
        return out

    async def open_vote(self, meeting_id: UUID) -> Vote | None:
        """Return the open vote of this meeting for the `subscribe` reconnect state."""
        return (
            await self.session.execute(
                select(Vote)
                .where(Vote.meeting_id == meeting_id, Vote.status == "open")
                .order_by(Vote.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def agenda_item_has_vote(self, item_id: UUID) -> bool:
        """Tell if this agenda item already has a vote that is not cancelled.

        An application agenda item accepts one vote at most. A cancelled vote does not
        count. Without this rule, a once-cancelled application vote would block every
        later vote on the same agenda item.
        """
        return (
            await self.session.execute(
                select(Vote.id)
                .where(Vote.agenda_item_id == item_id, Vote.status != "cancelled")
                .limit(1)
            )
        ).first() is not None

    async def application_state_kind(self, application_id: UUID) -> str | None:
        """Return the `state.kind` of the current application state, or `None`."""
        from app.modules.applications.models import Application
        from app.modules.flow.models import State

        return await self.session.scalar(
            select(State.kind)
            .join(Application, Application.current_state_id == State.id)
            .where(Application.id == application_id)
        )

    async def gremium_quorum_percent(self, gremium_id: UUID) -> int | None:
        """Return the default quorum of this gremium in percent of eligible voters.

        A result of `None` means the gremium sets no default quorum.
        """
        return (
            await self.session.execute(
                select(Gremium.quorum_percent).where(Gremium.id == gremium_id)
            )
        ).scalar_one_or_none()

    async def vote_eligible_count(self, gremium_id: UUID) -> int:
        """Return the roster size for the quorum: active members with a `vote.cast` role."""
        now = datetime.now(UTC)
        rows = (
            await self.session.execute(
                select(GremiumMembership.principal_id, GremiumRole.permissions)
                .join(GremiumRole, GremiumRole.id == GremiumMembership.gremium_role_id)
                .where(
                    GremiumMembership.gremium_id == gremium_id,
                    _time_valid_clause(now),
                )
            )
        ).all()
        return len({pid for pid, perms in rows if "vote.cast" in (perms or [])})
