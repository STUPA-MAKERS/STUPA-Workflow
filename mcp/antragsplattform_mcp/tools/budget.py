"""Budget tools: cost-centre tree, fiscal years, allocations, bookings, transfers,
accounts, and application↔budget binding."""

from __future__ import annotations

from typing import Literal

from mcp.server.fastmcp import FastMCP

from .. import schemas as S
from ..schemas import dump_create, dump_patch
from ._common import ToolGroup, api, params

group = ToolGroup()


@group.tool
async def list_budgets(gremium: str | None = None) -> dict:
    """List the cost-centre (budget) tree with allocations/rollups, optionally
    filtered to one committee."""
    return await api().get("/budgets", params=params(gremium=gremium))


@group.tool
async def get_budget_applications(budget_id: str) -> dict:
    """List applications bound to a cost centre (incl. subtree)."""
    return await api().get(f"/budgets/{budget_id}/applications")


@group.tool
async def create_budget(node: S.BudgetNodeCreate) -> dict:
    """Create a cost-centre (budget) node. gremiumId only on top-level nodes;
    parentId/gremiumId are immutable afterwards. Requires budget.manage."""
    return await api().post("/budgets", json=dump_create(node))


@group.tool
async def update_budget(budget_id: str, patch: S.BudgetNodeUpdate) -> dict:
    """Patch a cost-centre node (key/name/color/active/acceptedStateKeys/…).
    Requires budget.manage."""
    return await api().patch(f"/budgets/{budget_id}", json=dump_patch(patch))


@group.tool
async def delete_budget(budget_id: str) -> dict:
    """Delete a cost-centre node (conflicts if it has children). Requires budget.manage."""
    return await api().delete(f"/budgets/{budget_id}")


@group.tool
async def list_fiscal_years(budget_id: str) -> dict:
    """List the fiscal years of a top-level budget. Requires budget.manage."""
    return await api().get(f"/budgets/{budget_id}/fiscal-years")


@group.tool
async def create_fiscal_year(budget_id: str, year: int, active: bool = True) -> dict:
    """Create a fiscal year on a top-level budget (bounds derive from the budget's
    fiscal start day/month; overlapping years → 422). Requires budget.manage."""
    return await api().post(
        f"/budgets/{budget_id}/fiscal-years", json={"year": year, "active": active}
    )


@group.tool
async def update_fiscal_year(
    budget_id: str, fiscal_year_id: str, year: int | None = None, active: bool | None = None
) -> dict:
    """Patch a fiscal year (year/active). Requires budget.manage."""
    return await api().patch(
        f"/budgets/{budget_id}/fiscal-years/{fiscal_year_id}",
        json=params(year=year, active=active),
    )


@group.tool
async def set_allocation(budget_id: str, fiscal_year_id: str, allocated: str) -> dict:
    """Set the top-down allocation (Soll) of a cost centre for one fiscal year.
    allocated = decimal string; 422 if the children's sum exceeds the parent.
    Requires budget.manage."""
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
    """Book an expense/income on a cost centre. amount = decimal string; dates ISO. Optionally
    linked to an application and an invoice, plus metadata (correspondent, note, reference number,
    payment method, category, invoice/payment dates). Requires budget.manage. (Das Bankkonto ist
    kein Buchungs-Feld mehr — es wird nur beim Konten-Abgleich gesetzt, #fints-konten.)"""
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
    """List the bookings (expenses/income) of a cost centre."""
    return await api().get(f"/budgets/{budget_id}/expenses")


@group.tool
async def update_expense(expense_id: str, patch: S.ExpenseUpdate) -> dict:
    """Patch a booking (amount/description). Requires budget.manage."""
    return await api().patch(f"/budget-expenses/{expense_id}", json=dump_patch(patch))


@group.tool
async def delete_expense(expense_id: str) -> dict:
    """Delete a booking. Requires budget.manage."""
    return await api().delete(f"/budget-expenses/{expense_id}")


@group.tool
async def create_budget_transfer(transfer: S.TransferCreate) -> dict:
    """Transfer budget between two cost centres within one fiscal year.
    Requires budget.manage."""
    return await api().post("/budget-transfers", json=dump_create(transfer))


@group.tool
async def list_accounts() -> dict:
    """List bank accounts (for expense booking)."""
    return await api().get("/accounts")


@group.tool
async def create_account(account: S.AccountCreate) -> dict:
    """Create a bank account. Requires budget.manage."""
    return await api().post("/accounts", json=dump_create(account))


@group.tool
async def update_account(account_id: str, patch: S.AccountUpdate) -> dict:
    """Patch a bank account. Requires budget.manage."""
    return await api().patch(f"/accounts/{account_id}", json=dump_patch(patch))


@group.tool
async def delete_account(account_id: str) -> dict:
    """Delete a bank account. Requires budget.manage."""
    return await api().delete(f"/accounts/{account_id}")


@group.tool
async def assign_application_budget(
    application_id: str, budget_id: str | None
) -> dict:
    """Bind an application to a cost centre (null unbinds). The fiscal year derives
    from the top-level node's single active year. Requires budget.manage."""
    return await api().post(
        f"/applications/{application_id}/assign-budget", json={"budgetId": budget_id}
    )


@group.tool
async def move_application_fiscal_year(application_id: str, fiscal_year_id: str) -> dict:
    """Move an application's budget binding to another fiscal year.
    Requires budget.manage."""
    return await api().post(
        f"/applications/{application_id}/move-fiscal-year",
        json={"fiscalYearId": fiscal_year_id},
    )


def register(mcp: FastMCP) -> None:
    """Register the budget tool group."""
    group.register(mcp)
