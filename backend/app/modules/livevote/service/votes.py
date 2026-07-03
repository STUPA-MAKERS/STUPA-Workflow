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
        """Votes bound to the meeting(s), bundled per ``meeting_id``."""
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
        # Rebuild counts/leading + failed reason per vote from the ballots (reload
        # path; the live WS path already carries them). Batched (no N+1).
        tallies = await self._vote_tallies(rows)
        present_by_meeting = await self._present_by_meeting(meeting_ids)
        # Substitute ballots of absent delegators per (meeting, gremium) top up the
        # reveal denominator. Rule shared with the voting service
        # (``open_tally_revealed``) so both paths cannot drift. Queried only when an
        # OPEN, non-secret vote exists — only then it feeds a reveal decision
        # (closed/secret never reveal through this denominator).
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
            # Reveal rule as in the voting service: closed OR (non-secret AND all
            # EXPECTED ballots — present members + substitutes of absent delegators —
            # are in). Otherwise hide counts/leading (no interim leak).
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
        """``{meeting_id: number of present members}`` (reveal denominator)."""
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
        """``{(meeting_id, str(gremium_id)): n}`` active voting delegations whose
        delegator is NOT present (reveal-denominator top-up).

        Key matches ``vote.eligible_group`` (gremium UUID as text). Each such
        delegation yields one substitute ballot that counts into ``voted`` — hence
        it raises the expected denominator. Batched (no N+1)."""
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
        """``{vote_id: (counts, leading, failedReason)}`` from the ballots (reload).

        Loads ballots batched (open: ``ballot``, secret: ``secret_ballot``) and
        applies the pure tally logic. ``failedReason`` only for closed, failed votes."""
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
        """Currently open vote of this meeting (for ``subscribe`` reconnect state)."""
        return (
            await self.session.execute(
                select(Vote)
                .where(Vote.meeting_id == meeting_id, Vote.status == "open")
                .order_by(Vote.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def agenda_item_has_vote(self, item_id: UUID) -> bool:
        """Whether this TOP already has a NON-cancelled vote (application TOP: max one).

        Cancelled votes do NOT count: otherwise a once-cancelled application vote
        would block reopening forever (cancel then reopen)."""
        return (
            await self.session.execute(
                select(Vote.id)
                .where(Vote.agenda_item_id == item_id, Vote.status != "cancelled")
                .limit(1)
            )
        ).first() is not None

    async def application_state_kind(self, application_id: UUID) -> str | None:
        """``state.kind`` of the application's current state (``None`` without one)."""
        from app.modules.applications.models import Application
        from app.modules.flow.models import State

        return await self.session.scalar(
            select(State.kind)
            .join(Application, Application.current_state_id == State.id)
            .where(Application.id == application_id)
        )

    async def gremium_quorum_percent(self, gremium_id: UUID) -> int | None:
        """Default quorum (% of eligible voters) of this gremium, or ``None``."""
        return (
            await self.session.execute(
                select(Gremium.quorum_percent).where(Gremium.id == gremium_id)
            )
        ).scalar_one_or_none()

    async def vote_eligible_count(self, gremium_id: UUID) -> int:
        """Roster size for the quorum: active members holding a ``vote.cast`` role."""
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
