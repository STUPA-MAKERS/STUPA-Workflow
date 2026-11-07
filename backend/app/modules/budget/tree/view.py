"""Scoped tree view with the allocated, committed, requested and expended roll-up."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from itertools import groupby
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import func, select

from app.modules.applications.models import Application
from app.modules.budget import tree_rules
from app.modules.budget.tree.service_base import _ZERO, BudgetTreeServiceBase
from app.modules.budget.tree_models import Budget, BudgetAllocation, BudgetExpense
from app.modules.budget.tree_rules import _SEP
from app.modules.budget.tree_schemas import BudgetTreeNodeOut
from app.modules.flow.models import State


def _natural_path_key(path_key: str) -> tuple[Any, ...]:
    """Build the sort key for a natural path order.

    A numeric segment sorts as a number, so `VSM-10` comes after `VSM-9`. Every
    other segment sorts as a string. The tuple comparison stays type-pure: a
    numeric `(0, int)` segment and a string `(1, str)` segment already differ at
    position 0. A prefix path, that is a parent, sorts before its extensions.
    """
    return tuple((0, int(s)) if s.isdigit() else (1, s) for s in path_key.split("-"))


def _spent_per_app(expense_rows: Sequence[Sequence[Any]]) -> dict[object, Decimal]:
    """Sum the top-level expenses that are bound to an application, per application.

    Income does not reduce the binding of an application, so only expenses count.
    """
    spent = sorted(
        (
            (app_id, amount or _ZERO)
            for _path, _fy, amount, kind, app_id in expense_rows
            if kind == "expense" and app_id is not None
        ),
        key=lambda pair: str(pair[0]),
    )
    return {
        app_id: sum((amount for _, amount in group), _ZERO)
        for app_id, group in groupby(spent, key=lambda pair: pair[0])
    }


def _share(
    app_row: Sequence[Any],
    top_config: dict[str, tuple[set[str], set[str]]],
    spent_per_app: dict[object, Decimal],
) -> tuple[Literal["bound", "denied", "requested"], object, str, Decimal]:
    """Classify an application and compute the share it still binds or requests.

    The first path segment selects the state keys of the top budget. A bound
    application binds its approved amount, a requested one its requested amount, and
    both are reduced by the expenses already booked on it, so an expense never
    counts twice.
    """
    app_id, path, fy, amount, committed, state_key = app_row
    accepted, denied = top_config.get(path.split("-")[0], (set(), set()))
    bucket: Literal["bound", "denied", "requested"] = (
        "bound" if state_key in accepted else ("denied" if state_key in denied else "requested")
    )
    base = committed if bucket == "bound" else amount
    return bucket, fy, path, (base or _ZERO) - spent_per_app.get(app_id, _ZERO)


def _positive_rows(
    shares: Sequence[tuple[str, object, str, Decimal]], bucket: str
) -> list[tuple[object, str, Decimal | None]]:
    """Return the `(fy, path, amount)` rows of one bucket whose share is still positive."""
    return [(fy, path, rest) for kind, fy, path, rest in shares if kind == bucket and rest > _ZERO]


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
        the top budget. It then binds the approved amount of its decision,
        else the requested amount. It counts as requested when it is neither accepted nor
        denied. A denied application drops out.

        The nodes sort in natural order, so VSM-10 comes after VSM-9. Parents still come
        before children, so ``build_forest`` inherits the sibling order.

        A booking holds the real consumption (expended) or the income. An expense bound
        to an application carries ``application_id`` and replaces that share of the
        committed amount. Sub-bookings do not count, because the parent amount is
        already their sum. Only expenses reduce the binding of an application, income
        does not. A requested (in-flight) application is reduced by its booked expenses
        too, so an expense never counts twice. The first path segment of a node selects
        the accepted and the denied state keys of its top budget.

        Without a global ``budget.*`` permission only the assigned subtrees become
        roots: those whose ``view_gremium_id`` is one of the Gremien of the member.
        """
        nodes = sorted(
            (await self.session.execute(select(Budget))).scalars().all(),
            key=lambda b: _natural_path_key(b.path_key),
        )
        allocs = (await self.session.execute(select(BudgetAllocation))).scalars().all()
        app_rows = (
            await self.session.execute(
                select(
                    Application.id,
                    Budget.path_key,
                    Application.fiscal_year_id,
                    Application.amount,
                    func.coalesce(Application.approved_amount, Application.amount),
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
                .where(BudgetExpense.parent_expense_id.is_(None))
            )
        ).all()

        spent_per_app = _spent_per_app(expense_rows)
        top_config: dict[str, tuple[set[str], set[str]]] = {
            n.path_key: (set(n.accepted_state_keys or []), set(n.denied_state_keys or []))
            for n in nodes
            if n.parent_id is None
        }

        shares = tuple(_share(row, top_config, spent_per_app) for row in app_rows)
        bound_rows = _positive_rows(shares, "bound")
        requested_rows = _positive_rows(shares, "requested")

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
                n.decision_gremium_id,
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
        scoped = (
            forest
            if visible_gremium_ids is None
            else tree_rules.scope_forest(forest, set(visible_gremium_ids))
        )
        return [BudgetTreeNodeOut.model_validate(d) for d in scoped]
