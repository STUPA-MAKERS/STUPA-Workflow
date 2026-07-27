"""Scoped tree view with the allocated, committed, requested and expended roll-up."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select

from app.modules.applications.models import Application
from app.modules.budget import tree_rules
from app.modules.budget.tree.service_base import _ZERO, BudgetTreeServiceBase
from app.modules.budget.tree_models import Budget, BudgetAllocation, BudgetExpense
from app.modules.budget.tree_rules import _SEP
from app.modules.budget.tree_schemas import BudgetTreeNodeOut
from app.modules.flow.models import State


def _natural_path_key(path_key: str) -> tuple:
    """Build the sort key for a natural path order.

    A numeric segment sorts as a number, so `VSM-10` comes after `VSM-9`. Every
    other segment sorts as a string. The tuple comparison stays type-pure: a
    numeric `(0, int)` segment and a string `(1, str)` segment already differ at
    position 0. A prefix path, that is a parent, sorts before its extensions.
    """
    return tuple((0, int(s)) if s.isdigit() else (1, s) for s in path_key.split("-"))


class TreeViewOps(BudgetTreeServiceBase):
    """Build the scoped cost-center tree and answer node visibility."""

    async def can_view_node(self, budget_id: UUID, member_gremium_ids: set[UUID]) -> bool:
        """Tell if a member of a Gremium can see the node.

        The result is true when the node itself or an ancestor belongs to one of
        the Gremien of the member.
        """
        if not member_gremium_ids:
            return False
        node = await self._get_node(budget_id)
        segments = node.path_key.split(_SEP)
        prefixes = [_SEP.join(segments[: i + 1]) for i in range(len(segments))]
        rows = (
            await self.session.execute(
                select(Budget.view_gremium_id).where(Budget.path_key.in_(prefixes))
            )
        ).scalars()
        return any(v in member_gremium_ids for v in rows if v is not None)

    async def get_tree(
        self,
        *,
        gremium_id: UUID | None = None,
        visible_gremium_ids: set[UUID] | None = None,
    ) -> list[BudgetTreeNodeOut]:
        """Build the cost-center tree with the sums per fiscal year.

        Every node carries allocated, committed, requested and available. Each
        top-level budget classifies its applications. An application counts as
        committed when its current flow-state key is in `accepted_state_keys` of
        the top budget. It counts as requested when it is neither accepted nor
        denied. A denied application drops out.
        """
        nodes = list((await self.session.execute(select(Budget))).scalars().all())
        # Natural order puts VSM-10 after VSM-9 instead of sorting
        # lexicographically. Parents still come before children, so build_forest
        # inherits the sibling order.
        nodes.sort(key=lambda b: _natural_path_key(b.path_key))
        allocs = (await self.session.execute(select(BudgetAllocation))).scalars().all()
        app_rows = (
            await self.session.execute(
                select(
                    Application.id,
                    Budget.path_key,
                    Application.fiscal_year_id,
                    Application.amount,
                    State.key,
                )
                .join(Application, Application.budget_id == Budget.id)
                .join(State, State.id == Application.current_state_id)
                .where(
                    Application.amount.is_not(None),
                    Application.fiscal_year_id.is_not(None),
                )
            )
        ).all()

        # A booking holds the real consumption (expended) or the income. An
        # expense that binds to an application carries application_id. It
        # replaces that share of the committed amount of the application.
        expense_rows = (
            await self.session.execute(
                select(
                    Budget.path_key,
                    BudgetExpense.fiscal_year_id,
                    BudgetExpense.amount,
                    BudgetExpense.kind,
                    BudgetExpense.application_id,
                )
                .join(Budget, Budget.id == BudgetExpense.budget_id)
                # Do not count sub-bookings. The parent amount is the sum of the
                # children and is already included. Both would double the sum.
                .where(BudgetExpense.parent_expense_id.is_(None))
            )
        ).all()

        # Sum of the expenses bound to an application. Income does not reduce
        # the binding.
        spent_per_app: dict[object, Decimal] = {}
        for _path, _fy, amount, kind, app_id in expense_rows:
            if kind == "expense" and app_id is not None:
                spent_per_app[app_id] = spent_per_app.get(app_id, _ZERO) + (amount or _ZERO)

        # Top-budget config: the first path segment maps to the accepted and the
        # denied state keys.
        top_config: dict[str, tuple[set[str], set[str]]] = {
            n.path_key: (set(n.accepted_state_keys or []), set(n.denied_state_keys or []))
            for n in nodes
            if n.parent_id is None
        }

        bound_rows: list[tuple[object, str, Decimal | None]] = []
        requested_rows: list[tuple[object, str, Decimal | None]] = []
        for app_id, path, fy, amount, state_key in app_rows:
            accepted, denied = top_config.get(path.split("-")[0], (set(), set()))
            if state_key in accepted:
                # Reduce the binding by already booked expenses.
                spent = spent_per_app.get(app_id, _ZERO)
                remaining = (amount or _ZERO) - spent
                if remaining > _ZERO:
                    bound_rows.append((fy, path, remaining))
            elif state_key in denied:
                continue
            else:
                # Reduce a requested (in-flight) application by the booked
                # expenses too. The expense counts as spent, not twice.
                spent = spent_per_app.get(app_id, _ZERO)
                remaining = (amount or _ZERO) - spent
                if remaining > _ZERO:
                    requested_rows.append((fy, path, remaining))

        expended_rows = [
            (fy, path, amount)
            for path, fy, amount, kind, _app in expense_rows
            if kind == "expense"
        ]
        income_rows = [
            (fy, path, amount)
            for path, fy, amount, kind, _app in expense_rows
            if kind == "income"
        ]

        node_tuples = [
            (
                n.id,
                n.parent_id,
                n.gremium_id,
                n.key,
                n.path_key,
                n.name,
                n.currency,
                n.active,
                n.color,
                list(n.accepted_state_keys or []),
                list(n.denied_state_keys or []),
                n.fiscal_start_month,
                n.fiscal_start_day,
                bool(n.hidden_in_budget),
                n.view_gremium_id,
            )
            for n in nodes
        ]
        alloc_tuples = [(a.budget_id, a.fiscal_year_id, a.allocated) for a in allocs]
        forest = tree_rules.build_forest(
            node_tuples,
            alloc_tuples,
            bound_rows,
            requested_rows,
            expended_rows,
            income_rows,
            gremium_id=gremium_id,
        )
        # Gremium scope: without a global budget.* permission only the assigned
        # subtrees become roots. Their view_gremium_id is one of the Gremien of
        # the member.
        if visible_gremium_ids is not None:
            forest = tree_rules.scope_forest(forest, set(visible_gremium_ids))
        return [BudgetTreeNodeOut.model_validate(d) for d in forest]
