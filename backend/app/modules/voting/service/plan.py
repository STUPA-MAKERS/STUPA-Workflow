"""The locks and the steps of the votes on a version of a Haushaltsplan."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select

from app.modules.auth.principal import Principal
from app.modules.voting.models import Vote
from app.shared.errors import ConflictError

if TYPE_CHECKING:
    from app.modules.budget.tree.service import BudgetTreeService

from app.modules.voting.service.base import VotingServiceBase


class VotePlanOps(VotingServiceBase):
    """The locks and the steps of the votes on a version of a Haushaltsplan."""

    async def _locked_plan(
        self, plan_version_id: UUID | None, principal: Principal
    ) -> BudgetTreeService | None:
        """Lock the plan of a step vote and return the budget service, else `None`.

        The close holds the vote and takes the lock of the budget and of the plan here,
        before it writes its audit entry. A plan write takes the same order, because
        the other order ends in a deadlock that Postgres breaks with an error.
        """
        if plan_version_id is None:
            return None
        from app.modules.budget.tree.service import BudgetTreeService

        plans = BudgetTreeService(self.session, actor=principal.sub)
        await plans.lock_plan_of_version(plan_version_id)
        return plans

    async def _lock_plan_votes(self, vote_id: UUID) -> None:
        """Lock the draft and open votes of the plan version of a vote, when it has one.

        The open and the close of a plan vote call this before they lock their own
        vote, so each write to the votes of one version locks them in the same order.
        """
        plan_version_id = await self.session.scalar(
            select(Vote.plan_version_id).where(Vote.id == vote_id)
        )
        if plan_version_id is not None:
            await self.lock_for_plan_version(plan_version_id)

    async def _take_plan_step(self, vote: Vote, actor: str | None) -> None:
        """Bind a plan vote that opens to the step that waits for its Gremium.

        The open also keeps the file of the plan as it is now, because the protocol of
        the meeting shows the plan that the Gremium decided on (spec 000876).

        Raises:
            ConflictError: The vote has no meeting or the plan does not wait for the
                Gremium of the vote (``plan_step_not_waiting``), or another vote of
                the step is open (``plan_step_vote_runs``).
        """
        plan_version_id: UUID | None = getattr(vote, "plan_version_id", None)
        if plan_version_id is None:
            return
        if vote.meeting_id is None:
            raise ConflictError(
                "The vote of a plan step opens only in a meeting.",
                code="plan_step_not_waiting",
            )
        from app.modules.budget.tree.service import BudgetTreeService

        budget = BudgetTreeService(self.session, actor=actor)
        await budget.take_step_vote(plan_version_id, vote.id, UUID(vote.eligible_group))
        await budget.keep_vote_snapshot(plan_version_id, vote.id, datetime.now(UTC).date())

    async def lock_for_plan_version(self, plan_version_id: UUID) -> None:
        """Lock the draft and open votes of a plan version, before its plan row.

        The close of a step vote locks the vote first and the plan after it. The move
        back to draft takes the same order with this call, because the other order
        ends in a deadlock that Postgres breaks with an error.
        """
        await self.session.execute(
            select(Vote.id)
            .where(
                Vote.plan_version_id == plan_version_id,
                Vote.status.in_(("draft", "open")),
            )
            .order_by(Vote.id)
            .with_for_update()
        )
