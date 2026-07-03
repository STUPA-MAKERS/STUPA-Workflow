"""Public facade of the budget tree service.

:class:`BudgetTreeService` combines the concerns — the router (``tree_router``)
binds to exactly this class. The implementation lives in the ops classes:

* :class:`~.nodes.NodeOps` — cost-centre CRUD (via :class:`~.revert.RevertOps`)
* :class:`~.fiscal_years.FiscalYearOps` — fiscal years on top-level budgets
* :class:`~.allocations.AllocationOps` — top-down allocations (via ``RevertOps``)
* :class:`~.applications.AssignmentOps` — application ↔ budget assignment
* :class:`~.expenses.ExpenseOps` — bookings (via :class:`~.subbookings.SubBookingOps`)
* :class:`~.subbookings.SubBookingOps` — sub-bookings + statement-file import
* :class:`~.accounts.AccountOps` — bank accounts + FinTS connection
* :class:`~.invoices.InvoiceOps` — invoices + ZUGFeRD import
* :class:`~.transfers.TransferOps` — cost-centre transfers
* :class:`~.revert.RevertOps` — audit-log revert of budget mutations
* :class:`~.view.TreeViewOps` — scoped tree view with roll-up
"""

from __future__ import annotations

from app.modules.budget.tree.accounts import AccountOps
from app.modules.budget.tree.applications import AssignmentOps
from app.modules.budget.tree.fiscal_years import FiscalYearOps
from app.modules.budget.tree.invoices import InvoiceOps
from app.modules.budget.tree.revert import RevertOps
from app.modules.budget.tree.subbookings import SubBookingOps
from app.modules.budget.tree.transfers import TransferOps
from app.modules.budget.tree.view import TreeViewOps


class BudgetTreeService(
    FiscalYearOps,
    AssignmentOps,
    SubBookingOps,
    AccountOps,
    InvoiceOps,
    TransferOps,
    RevertOps,
    TreeViewOps,
):
    """DB-backed cost-centre tree operations (bound to one session)."""
