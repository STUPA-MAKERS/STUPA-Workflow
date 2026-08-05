"""Public facade of the budget tree service.

`BudgetTreeService` combines the concerns. The router (`tree_router`) binds to
exactly this class. The implementation lives in the ops classes:

`nodes.NodeOps` — cost-center CRUD (through `revert.RevertOps`).
`fiscal_years.FiscalYearOps` — fiscal years on top-level budgets.
`allocations.AllocationOps` — top-down allocations (through `RevertOps`).
`applications.AssignmentOps` — application to budget assignment.
`expenses.ExpenseOps` — bookings (through `subbookings.SubBookingOps`).
`subbookings.SubBookingOps` — sub-bookings of a booking.
`invoices.InvoiceOps` — invoices and ZUGFeRD import.
`transfers.TransferOps` — cost-center transfers.
`revert.RevertOps` — audit-log revert of budget mutations.
`view.TreeViewOps` — scoped tree view with roll-up.
"""

from __future__ import annotations

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
    InvoiceOps,
    TransferOps,
    RevertOps,
    TreeViewOps,
):
    """Cost-center tree operations on the database, bound to one session."""
