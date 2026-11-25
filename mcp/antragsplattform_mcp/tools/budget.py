"""Budget tools.

This group covers the cost center tree, fiscal years, allocations, bookings,
transfers, and the binding between an application and a budget.
"""

from __future__ import annotations

from typing import Literal

from mcp.server.fastmcp import FastMCP

from .. import schemas as S
from ..schemas import dump_create, dump_patch
from ._common import ToolGroup, api, params
from .meetings import download_to

group = ToolGroup()


@group.tool
async def list_budgets(gremium: str | None = None) -> dict:
    """List the cost center (budget) tree with its allocations and rollups.

    Each node carries `decisionGremiumId` (its own deciding Gremium),
    `effectiveDecisionGremiumId` (own value, else the nearest ancestor's) and
    `decisionGremiumSourceId` (the node that supplies the effective value).

    Args:
        gremium: Limit the tree to one Gremium.
    """
    return await api().get("/budgets", params=params(gremium=gremium))


@group.tool
async def get_budget_applications(budget_id: str) -> dict:
    """List the applications bound to a cost center and to its subtree."""
    return await api().get(f"/budgets/{budget_id}/applications")


@group.tool
async def create_budget(node: S.BudgetNodeCreate) -> dict:
    """Create a cost center (budget) node.

    Set `gremiumId` on a top-level node only. After creation, `parentId` and
    `gremiumId` stay fixed. `decisionGremiumId` names the Gremium that decides on
    spending from the node and its subtree. Requires budget.structure.
    """
    return await api().post("/budgets", json=dump_create(node))


@group.tool
async def update_budget(budget_id: str, patch: S.BudgetNodeUpdate) -> dict:
    """Patch a cost center node.

    You can change `key`, `name`, `color`, `active` and more. Approved and denied
    come from the flags of the flow states, not from the cost center.
    `decisionGremiumId` sets the deciding Gremium (null clears it; the node then
    inherits from its ancestors). An unknown Gremium gives 422
    `decision_gremium_invalid`, and an unknown `viewGremiumId` gives 422
    `view_gremium_invalid`. A key that a sibling has gives 409 `budget_key_exists`.
    In a budget with a plan, a new `key` or `name` of a cost center below the top
    level gives 409 `plan_draft_only`: use `rename_plan_line` in a draft.
    Requires budget.structure.
    """
    return await api().patch(f"/budgets/{budget_id}", json=dump_patch(patch))


@group.tool
async def delete_budget(budget_id: str) -> dict:
    """Delete a cost center node.

    The call fails with a conflict when the node has children, and with 409
    `budget_in_plan` when a decided version of a Haushaltsplan has a line for it.
    Requires budget.structure.
    """
    return await api().delete(f"/budgets/{budget_id}")


@group.tool
async def list_fiscal_years(budget_id: str) -> dict:
    """List the fiscal years of a top-level budget. Needs a logged-in principal."""
    return await api().get(f"/budgets/{budget_id}/fiscal-years")


@group.tool
async def create_fiscal_year(budget_id: str, year: int, active: bool = True) -> dict:
    """Create a fiscal year on a top-level budget.

    The bounds come from the fiscal start day and month of the budget. A year that
    overlaps another year gives a 422. Requires budget.structure.
    """
    return await api().post(
        f"/budgets/{budget_id}/fiscal-years", json={"year": year, "active": active}
    )


@group.tool
async def update_fiscal_year(
    budget_id: str, fiscal_year_id: str, year: int | None = None, active: bool | None = None
) -> dict:
    """Patch the year or the active flag of a fiscal year.

    A new year gives 409 `fiscal_year_closed` for a closed year and 409
    `fiscal_year_has_plan` while the Haushaltsplan of the year has a version that
    left the draft. Requires budget.structure.
    """
    return await api().patch(
        f"/budgets/{budget_id}/fiscal-years/{fiscal_year_id}",
        json=params(year=year, active=active),
    )


@group.tool
async def close_fiscal_year(budget_id: str, fiscal_year_id: str) -> dict:
    """Close a fiscal year, so no money or plan write changes it.

    The call gives 409 `plan_in_progress` while a version of its Haushaltsplan waits
    for a step. Requires budget.structure.
    """
    return await api().post(f"/budgets/{budget_id}/fiscal-years/{fiscal_year_id}/close")


@group.tool
async def reopen_fiscal_year(budget_id: str, fiscal_year_id: str) -> dict:
    """Open a closed fiscal year again. Requires budget.structure."""
    return await api().post(f"/budgets/{budget_id}/fiscal-years/{fiscal_year_id}/reopen")


@group.tool
async def delete_fiscal_year(budget_id: str, fiscal_year_id: str) -> dict:
    """Delete a fiscal year that nothing uses.

    A Haushaltsplan that is only a draft goes with the year. The call gives 409
    `fiscal_year_has_plan` for a plan with a version that left the draft, 409
    `fiscal_year_closed` for a closed year and 409 `fiscal_year_has_...` while
    allocations, bookings or applications use the year. Requires budget.structure.
    """
    return await api().delete(f"/budgets/{budget_id}/fiscal-years/{fiscal_year_id}")


@group.tool
async def set_allocation(budget_id: str, fiscal_year_id: str, allocated: str) -> dict:
    """Set the top-down allocation of a cost center for one fiscal year.

    The call gives a 422 when the sum of the children is more than the parent, and
    409 `allocation_from_plan` for a fiscal year with a Haushaltsplan: there the plan
    in force sets the allocations. Requires budget.structure.

    Args:
        allocated: The allocated amount as a decimal string.
    """
    return await api().put(
        f"/budgets/{budget_id}/allocations/{fiscal_year_id}",
        json={"allocated": allocated},
    )


@group.tool
async def book_expense(
    budget_id: str,
    amount: str,
    description: str,
    kind: Literal["expense", "income"] = "expense",
    fiscal_year_id: str | None = None,
    application_id: str | None = None,
    invoice_date: str | None = None,
    payment_date: str | None = None,
    correspondent: str | None = None,
    note: str | None = None,
    reference_number: str | None = None,
    payment_method: Literal["ueberweisung", "bar", "lastschrift", "karte", "paypal"] | None = None,
    category: str | None = None,
    invoice_id: str | None = None,
    order_id: str | None = None,
) -> dict:
    """Book an expense or an income on a cost center.

    You can link the booking to an application and to an invoice. You can also give a
    correspondent, a note, a reference number, a payment method, a category and the
    invoice and payment dates. Requires budget.book.

    `order_id` names the Bestellung that the expense paid. It needs the
    `application_id` of that Bestellung (422 `order_application_mismatch`), and an
    income cannot name one.

    Args:
        amount: The amount as a decimal string.
        invoice_date: The invoice date in ISO format.
        payment_date: The payment date in ISO format.
    """
    return await api().post(
        f"/budgets/{budget_id}/expenses",
        json=params(
            amount=amount, description=description, kind=kind,
            fiscalYearId=fiscal_year_id, applicationId=application_id,
            invoiceDate=invoice_date, paymentDate=payment_date,
            correspondent=correspondent, note=note, referenceNumber=reference_number,
            paymentMethod=payment_method, category=category, invoiceId=invoice_id,
            orderId=order_id,
        ),
    )


@group.tool
async def list_budget_expenses(budget_id: str) -> dict:
    """List the bookings (expenses and income) of a cost center."""
    return await api().get(f"/budgets/{budget_id}/expenses")


@group.tool
async def update_expense(expense_id: str, patch: S.ExpenseUpdate) -> dict:
    """Patch the amount or the description of a booking. Requires budget.book."""
    return await api().patch(f"/budget-expenses/{expense_id}", json=dump_patch(patch))


@group.tool
async def delete_expense(expense_id: str) -> dict:
    """Delete a booking. Requires budget.book."""
    return await api().delete(f"/budget-expenses/{expense_id}")


@group.tool
async def create_budget_transfer(transfer: S.TransferCreate) -> dict:
    """Transfer budget between two cost centers inside one fiscal year.

    Requires budget.book.
    """
    return await api().post("/budget-transfers", json=dump_create(transfer))


@group.tool
async def assign_application_budget(
    application_id: str, budget_id: str | None
) -> dict:
    """Bind an application to a cost center.

    Pass null to remove the binding. The fiscal year is the current year of the top-level
    node: its only active open year, else the active open year that holds today. While
    the application sits in a vote state whose Gremium comes from the cost center, the
    server refuses the change with 409
    `budget_locked_by_vote`. Requires application.manage.
    """
    return await api().post(
        f"/applications/{application_id}/assign-budget", json={"budgetId": budget_id}
    )


@group.tool
async def move_application_fiscal_year(application_id: str, fiscal_year_id: str) -> dict:
    """Move the budget binding of an application to another fiscal year.

    Requires application.manage.
    """
    return await api().post(
        f"/applications/{application_id}/move-fiscal-year",
        json={"fiscalYearId": fiscal_year_id},
    )


@group.tool
async def book_application_expense(
    application_id: str,
    amount: str,
    description: str,
    kind: Literal["expense", "income"] = "expense",
    invoice_date: str | None = None,
    payment_date: str | None = None,
    correspondent: str | None = None,
    note: str | None = None,
    reference_number: str | None = None,
    payment_method: Literal["ueberweisung", "bar", "lastschrift", "karte", "paypal"] | None = None,
    category: str | None = None,
    invoice_id: str | None = None,
) -> dict:
    """Book an expense or an income on an application.

    The booking takes the cost center and the fiscal year of the application. Requires
    budget.book.
    """
    return await api().post(
        "/expenses",
        json=params(
            applicationId=application_id, amount=amount, description=description, kind=kind,
            invoiceDate=invoice_date, paymentDate=payment_date, correspondent=correspondent,
            note=note, referenceNumber=reference_number, paymentMethod=payment_method,
            category=category, invoiceId=invoice_id,
        ),
    )


@group.tool
async def create_sub_booking(
    expense_id: str,
    amount: str,
    description: str,
    invoice_date: str | None = None,
    payment_date: str | None = None,
    correspondent: str | None = None,
    note: str | None = None,
    reference_number: str | None = None,
    payment_method: Literal["ueberweisung", "bar", "lastschrift", "karte", "paypal"] | None = None,
    category: str | None = None,
) -> dict:
    """Create a sub-booking of a booking by hand; it takes the cost center, the year and
    the kind of the parent. Requires budget.book.
    """
    return await api().post(
        f"/budget-expenses/{expense_id}/sub-bookings",
        json=params(
            amount=amount, description=description, invoiceDate=invoice_date,
            paymentDate=payment_date, correspondent=correspondent, note=note,
            referenceNumber=reference_number, paymentMethod=payment_method, category=category,
        ),
    )


@group.tool
async def list_budget_transfers(
    transfer_id: str | None = None,
    budget: str | None = None,
    fiscal_year: str | None = None,
    q: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> dict:
    """List the transfers (Umbuchungen) as single rows, page by page.

    Args:
        transfer_id: One transfer only.
        budget: A cost center; it matches either side and includes the subtree.
        fiscal_year: A fiscal year id.
        q: Search in the description and the note.
    """
    return await api().get(
        "/budget-transfers",
        params=params(
            id=transfer_id, budget=budget, fiscalYear=fiscal_year, q=q, limit=limit,
            offset=offset,
        ),
    )


@group.tool
async def update_budget_transfer(
    transfer_id: str,
    amount: str | None = None,
    description: str | None = None,
    note: str | None = None,
    invoice_date: str | None = None,
    payment_date: str | None = None,
) -> dict:
    """Change both legs of a transfer at once; the two cost centers stay. Requires budget.book."""
    return await api().patch(
        f"/budget-transfers/{transfer_id}",
        json=params(
            amount=amount, description=description, note=note, invoiceDate=invoice_date,
            paymentDate=payment_date,
        ),
    )


@group.tool
async def delete_budget_transfer(transfer_id: str) -> dict:
    """Delete a transfer, that is both of its bookings. Requires budget.book."""
    await api().delete(f"/budget-transfers/{transfer_id}")
    return {"deleted": True}


@group.tool
async def fiscal_year_close_check(budget_id: str, fiscal_year_id: str) -> dict:
    """Say what the close of a fiscal year leaves open: Anträge not in an end state and a
    Nachtrag of the plan in draft. Call it before `close_fiscal_year`.
    """
    return await api().get(f"/budgets/{budget_id}/fiscal-years/{fiscal_year_id}/close-check")


@group.tool
async def export_budget_xlsx(
    target_path: str,
    gremium: str | None = None,
    node: str | None = None,
    fiscal_year: str | None = None,
    overwrite: bool = False,
) -> dict:
    """Export the budget tree as `.xlsx` to a local file, filtered like the dashboard."""
    return await download_to(
        "GET",
        "/budget/export.xlsx",
        target_path,
        overwrite=overwrite,
        fallback="haushalt.xlsx",
        query=params(gremium=gremium, node=node, fiscalYear=fiscal_year),
    )


@group.tool
async def export_expenses_xlsx(
    target_path: str,
    budget: str | None = None,
    fiscal_year: str | None = None,
    kind: Literal["expense", "income"] | None = None,
    q: str | None = None,
    ids: list[str] | None = None,
    overwrite: bool = False,
) -> dict:
    """Export the bookings as `.xlsx` to a local file, with the filters of `list_expenses`."""
    return await download_to(
        "GET",
        "/expenses/export.xlsx",
        target_path,
        overwrite=overwrite,
        fallback="buchungen.xlsx",
        query=params(budget=budget, fiscalYear=fiscal_year, kind=kind, q=q, ids=ids),
    )


def register(mcp: FastMCP) -> None:
    """Register the budget tool group."""
    group.register(mcp)
