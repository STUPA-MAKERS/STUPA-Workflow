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

group = ToolGroup()


@group.tool
async def list_budgets(gremium: str | None = None) -> dict:
    """List the cost center (budget) tree with its allocations and rollups.

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
    `gremiumId` stay fixed. Requires budget.manage.
    """
    return await api().post("/budgets", json=dump_create(node))


@group.tool
async def update_budget(budget_id: str, patch: S.BudgetNodeUpdate) -> dict:
    """Patch a cost center node.

    You can change `key`, `name`, `color`, `active`, `acceptedStateKeys` and more.
    Requires budget.manage.
    """
    return await api().patch(f"/budgets/{budget_id}", json=dump_patch(patch))


@group.tool
async def delete_budget(budget_id: str) -> dict:
    """Delete a cost center node.

    The call fails with a conflict when the node has children.
    Requires budget.manage.
    """
    return await api().delete(f"/budgets/{budget_id}")


@group.tool
async def list_fiscal_years(budget_id: str) -> dict:
    """List the fiscal years of a top-level budget. Requires budget.manage."""
    return await api().get(f"/budgets/{budget_id}/fiscal-years")


@group.tool
async def create_fiscal_year(budget_id: str, year: int, active: bool = True) -> dict:
    """Create a fiscal year on a top-level budget.

    The bounds come from the fiscal start day and month of the budget. A year that
    overlaps another year gives a 422. Requires budget.manage.
    """
    return await api().post(
        f"/budgets/{budget_id}/fiscal-years", json={"year": year, "active": active}
    )


@group.tool
async def update_fiscal_year(
    budget_id: str, fiscal_year_id: str, year: int | None = None, active: bool | None = None
) -> dict:
    """Patch the year or the active flag of a fiscal year. Requires budget.manage."""
    return await api().patch(
        f"/budgets/{budget_id}/fiscal-years/{fiscal_year_id}",
        json=params(year=year, active=active),
    )


@group.tool
async def set_allocation(budget_id: str, fiscal_year_id: str, allocated: str) -> dict:
    """Set the top-down allocation of a cost center for one fiscal year.

    The call gives a 422 when the sum of the children is more than the parent.
    Requires budget.manage.

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
) -> dict:
    """Book an expense or an income on a cost center.

    You can link the booking to an application and to an invoice. You can also give a
    correspondent, a note, a reference number, a payment method, a category and the
    invoice and payment dates. Requires budget.manage.

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
        ),
    )


@group.tool
async def list_budget_expenses(budget_id: str) -> dict:
    """List the bookings (expenses and income) of a cost center."""
    return await api().get(f"/budgets/{budget_id}/expenses")


@group.tool
async def update_expense(expense_id: str, patch: S.ExpenseUpdate) -> dict:
    """Patch the amount or the description of a booking. Requires budget.manage."""
    return await api().patch(f"/budget-expenses/{expense_id}", json=dump_patch(patch))


@group.tool
async def delete_expense(expense_id: str) -> dict:
    """Delete a booking. Requires budget.manage."""
    return await api().delete(f"/budget-expenses/{expense_id}")


@group.tool
async def create_budget_transfer(transfer: S.TransferCreate) -> dict:
    """Transfer budget between two cost centers inside one fiscal year.

    Requires budget.manage.
    """
    return await api().post("/budget-transfers", json=dump_create(transfer))


@group.tool
async def assign_application_budget(
    application_id: str, budget_id: str | None
) -> dict:
    """Bind an application to a cost center.

    Pass null to remove the binding. The fiscal year comes from the single active year
    of the top-level node. Requires budget.manage.
    """
    return await api().post(
        f"/applications/{application_id}/assign-budget", json={"budgetId": budget_id}
    )


@group.tool
async def move_application_fiscal_year(application_id: str, fiscal_year_id: str) -> dict:
    """Move the budget binding of an application to another fiscal year.

    Requires budget.manage.
    """
    return await api().post(
        f"/applications/{application_id}/move-fiscal-year",
        json={"fiscalYearId": fiscal_year_id},
    )


def register(mcp: FastMCP) -> None:
    """Register the budget tool group."""
    group.register(mcp)
