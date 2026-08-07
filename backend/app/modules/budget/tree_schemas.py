"""API schemas of the budget tree.

`_CamelModel` supplies the camelCase aliases. Money uses `Decimal`
(numeric(12,2)) and a date uses `date`. The server maintains `pathKey`. A
request never accepts it. It appears in out DTOs only.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.modules.budget.schemas import _CamelModel

# Money cap that matches the DB column `numeric(12, 2)`. An input field applies
# it as `le`, so an oversized amount gives a clean 422 instead of a
# numeric-overflow 500.
_MAX_AMOUNT = Decimal("9999999999.99")


class BudgetNodeCreate(_CamelModel):
    """Create a cost center.

    `parentId=null` means top level, and `gremiumId` is then required.
    `fiscalStartMonth` and `fiscalStartDay` set the fiscal cutoff. They apply at
    the top level only and default to Jan 1.
    """

    key: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    parent_id: UUID | None = Field(default=None, alias="parentId")
    gremium_id: UUID | None = Field(default=None, alias="gremiumId")
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    active: bool = True
    color: str | None = None
    fiscal_start_month: int = Field(default=1, ge=1, le=12, alias="fiscalStartMonth")
    # 1..28: the cutoff must exist in EVERY month. Days 29 to 31 would raise a
    # `date(...)` ValueError. The 500 that follows leaves the budget unusable.
    fiscal_start_day: int = Field(default=1, ge=1, le=28, alias="fiscalStartDay")


class BudgetNodeUpdate(_CamelModel):
    """Partially update a cost center.

    The key and the parent stay immutable to keep the path stable. `None` means
    unchanged. `color=""` clears the color. `acceptedStateKeys`,
    `deniedStateKeys` and `fiscalStart*` make sense at the top level only.
    """

    key: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    active: bool | None = None
    color: str | None = None
    accepted_state_keys: list[str] | None = Field(default=None, alias="acceptedStateKeys")
    denied_state_keys: list[str] | None = Field(default=None, alias="deniedStateKeys")
    hidden_in_budget: bool | None = Field(default=None, alias="hiddenInBudget")
    # Visibility Gremium. `None` in the payload clears the assignment.
    view_gremium_id: UUID | None = Field(default=None, alias="viewGremiumId")
    fiscal_start_month: int | None = Field(default=None, ge=1, le=12, alias="fiscalStartMonth")
    # 1..28: see `BudgetNodeCreate`. The cutoff must exist in every month.
    fiscal_start_day: int | None = Field(default=None, ge=1, le=28, alias="fiscalStartDay")


class BudgetNodeOut(_CamelModel):
    """Base data of a node."""

    id: UUID
    parent_id: UUID | None = Field(alias="parentId")
    gremium_id: UUID | None = Field(alias="gremiumId")
    key: str
    path_key: str = Field(alias="pathKey")
    name: str
    currency: str
    active: bool
    color: str | None = None
    accepted_state_keys: list[str] = Field(default_factory=list, alias="acceptedStateKeys")
    denied_state_keys: list[str] = Field(default_factory=list, alias="deniedStateKeys")
    hidden_in_budget: bool = Field(default=False, alias="hiddenInBudget")
    view_gremium_id: UUID | None = Field(default=None, alias="viewGremiumId")
    fiscal_start_month: int = Field(default=1, alias="fiscalStartMonth")
    fiscal_start_day: int = Field(default=1, alias="fiscalStartDay")


class AllocationView(_CamelModel):
    """Budget view of a node in ONE fiscal year.

    `committed` is `bound + expended`, the total consumption. It stays for
    backward compatibility. `available = allocated - bound - expended + income`.
    """

    fiscal_year_id: UUID = Field(alias="fiscalYearId")
    allocated: Decimal
    # Bound: accepted applications, reduced pro rata by the expenses bound to them.
    bound: Decimal = Decimal("0")
    # Expended: actual expenses, kind='expense'.
    expended: Decimal = Decimal("0")
    # Income, kind='income'. It raises the available budget.
    income: Decimal = Decimal("0")
    committed: Decimal
    requested: Decimal = Decimal("0")
    available: Decimal


class BudgetTreeNodeOut(_CamelModel):
    """Tree node with per-fiscal-year sums and recursive children for `GET /budgets`."""

    id: UUID
    parent_id: UUID | None = Field(alias="parentId")
    gremium_id: UUID | None = Field(alias="gremiumId")
    key: str
    path_key: str = Field(alias="pathKey")
    name: str
    currency: str
    active: bool
    color: str | None = None
    accepted_state_keys: list[str] = Field(default_factory=list, alias="acceptedStateKeys")
    denied_state_keys: list[str] = Field(default_factory=list, alias="deniedStateKeys")
    hidden_in_budget: bool = Field(default=False, alias="hiddenInBudget")
    view_gremium_id: UUID | None = Field(default=None, alias="viewGremiumId")
    fiscal_start_month: int = Field(default=1, alias="fiscalStartMonth")
    fiscal_start_day: int = Field(default=1, alias="fiscalStartDay")
    by_fiscal_year: list[AllocationView] = Field(default_factory=list, alias="byFiscalYear")
    children: list[BudgetTreeNodeOut] = Field(default_factory=list)


class FiscalYearCreate(_CamelModel):
    """Create a fiscal year from the year alone.

    The start and the end derive from the budget cutoff.
    """

    year: int = Field(ge=1900, le=2200)
    active: bool = True


class FiscalYearUpdate(_CamelModel):
    """Update the year or the active flag of a fiscal year.

    The service checks again that the fiscal years stay disjoint.
    """

    year: int | None = Field(default=None, ge=1900, le=2200)
    active: bool | None = None


class FiscalYearOut(_CamelModel):
    """Fiscal-year base data.

    `display` is `YYYY` for a Jan 1 cutoff, else `YYYY/YY`.
    """

    id: UUID
    budget_id: UUID = Field(alias="budgetId")
    year: int
    display: str
    start_date: date = Field(alias="startDate")
    end_date: date = Field(alias="endDate")
    active: bool


class AllocationSet(_CamelModel):
    """Set the top-down allocation with `PUT .../allocations/{fiscalYearId}`."""

    allocated: Decimal = Field(ge=0, allow_inf_nan=False)


class AllocationOut(_CamelModel):
    """Result of an allocation."""

    budget_id: UUID = Field(alias="budgetId")
    fiscal_year_id: UUID = Field(alias="fiscalYearId")
    allocated: Decimal


class AssignBudgetRequest(_CamelModel):
    """Assign an application to a cost center and set the fiscal year.

    `budgetId=null` clears the assignment and sets `fiscalYearId` to null too.
    `fiscalYearId` is optional. A given value must belong to the top budget of
    the cost center. Without a value the service derives the single active
    fiscal year. It otherwise demands an explicit choice with a 422, as with
    expenses.
    """

    budget_id: UUID | None = Field(default=None, alias="budgetId")
    fiscal_year_id: UUID | None = Field(default=None, alias="fiscalYearId")


class MoveFiscalYearRequest(_CamelModel):
    """Move an application to another fiscal year (of the top budget)."""

    fiscal_year_id: UUID = Field(alias="fiscalYearId")


class AssignBudgetOut(_CamelModel):
    """Result of a cost center and fiscal year assignment."""

    application_id: UUID = Field(alias="applicationId")
    budget_id: UUID | None = Field(alias="budgetId")
    fiscal_year_id: UUID | None = Field(alias="fiscalYearId")


class BudgetApplicationOut(_CamelModel):
    """Application in a cost center and its subtree, for the budget drilldown list.

    Money uses `Decimal`. `stage` comes from the `budget_entry` and can be None.
    """

    application_id: UUID = Field(alias="applicationId")
    title: str | None = None
    budget_id: UUID | None = Field(default=None, alias="budgetId")
    path_key: str | None = Field(default=None, alias="pathKey")
    fiscal_year_id: UUID | None = Field(default=None, alias="fiscalYearId")
    amount: Decimal | None = None
    currency: str | None = None
    stage: str | None = None
    state_id: UUID | None = Field(default=None, alias="stateId")
    # Current flow state (i18n label + color) for the status column.
    state_label: dict[str, str] | None = Field(default=None, alias="stateLabel")
    state_color: str | None = Field(default=None, alias="stateColor")
    created_at: datetime = Field(alias="createdAt")


ExpenseKind = Literal["expense", "income"]
# Payment method: bank transfer, cash, direct debit, card, PayPal.
PaymentMethod = Literal["ueberweisung", "bar", "lastschrift", "karte", "paypal"]


class ExpenseCreate(_CamelModel):
    """Book an expense or income against a cost center and a fiscal year.

    `budgetId` is required for a standalone booking. A bound booking inherits
    the cost center from the application, and the server then ignores
    `budgetId` and `fiscalYearId`. `applicationId` binds the booking and
    replaces its binding pro rata. It is allowed for `kind='expense'` only.
    `fiscalYearId` is optional for a standalone expense. Without it the server
    picks the single active fiscal year of the top budget. An ambiguous or
    missing year gives a 422.
    """

    amount: Decimal = Field(gt=0, le=_MAX_AMOUNT, allow_inf_nan=False)
    description: str = Field(min_length=1)
    kind: ExpenseKind = "expense"
    budget_id: UUID | None = Field(default=None, alias="budgetId")
    fiscal_year_id: UUID | None = Field(default=None, alias="fiscalYearId")
    application_id: UUID | None = Field(default=None, alias="applicationId")
    invoice_date: date | None = Field(default=None, alias="invoiceDate")
    payment_date: date | None = Field(default=None, alias="paymentDate")
    correspondent: str | None = Field(default=None)
    note: str | None = Field(default=None)
    reference_number: str | None = Field(default=None, alias="referenceNumber")
    payment_method: PaymentMethod | None = Field(default=None, alias="paymentMethod")
    category: str | None = Field(default=None)
    invoice_id: UUID | None = Field(default=None, alias="invoiceId")

    @model_validator(mode="after")
    def _income_not_linkable(self) -> ExpenseCreate:
        if self.kind == "income" and self.application_id is not None:
            raise ValueError("income cannot be linked to an application")
        return self


class SubBookingCreate(_CamelModel):
    """Create a sub-booking by hand.

    The sub-booking inherits the cost center, the fiscal year and the kind from
    the parent. This schema carries the own values only: amount, description and
    metadata.
    """

    amount: Decimal = Field(gt=0, le=_MAX_AMOUNT, allow_inf_nan=False)
    description: str = Field(min_length=1)
    invoice_date: date | None = Field(default=None, alias="invoiceDate")
    payment_date: date | None = Field(default=None, alias="paymentDate")
    correspondent: str | None = Field(default=None)
    note: str | None = Field(default=None)
    reference_number: str | None = Field(default=None, alias="referenceNumber")
    payment_method: PaymentMethod | None = Field(default=None, alias="paymentMethod")
    category: str | None = Field(default=None)


class ExpenseUpdate(_CamelModel):
    """Update a booked expense or income.

    The amount, the description, the cost center and the optional metadata are
    editable. The fiscal year and the application binding stay fixed to keep
    the booking stable. The server writes the set fields only. An explicit
    `null` clears an optional field. `budgetId` is the exception, because the
    FK is required.
    """

    amount: Decimal | None = Field(default=None, gt=0, le=_MAX_AMOUNT, allow_inf_nan=False)
    description: str | None = Field(default=None, min_length=1)
    budget_id: UUID | None = Field(default=None, alias="budgetId")
    invoice_date: date | None = Field(default=None, alias="invoiceDate")
    payment_date: date | None = Field(default=None, alias="paymentDate")
    correspondent: str | None = Field(default=None)
    note: str | None = Field(default=None)
    reference_number: str | None = Field(default=None, alias="referenceNumber")
    payment_method: PaymentMethod | None = Field(default=None, alias="paymentMethod")
    category: str | None = Field(default=None)
    invoice_id: UUID | None = Field(default=None, alias="invoiceId")

    @model_validator(mode="after")
    def _at_least_one(self) -> ExpenseUpdate:
        if not self.model_fields_set:
            raise ValueError("at least one field required")
        return self


class ExpenseOut(_CamelModel):
    """Base data of a booked expense or income."""

    id: UUID
    budget_id: UUID = Field(alias="budgetId")
    path_key: str | None = Field(default=None, alias="pathKey")
    fiscal_year_id: UUID = Field(alias="fiscalYearId")
    kind: ExpenseKind = "expense"
    amount: Decimal
    currency: str
    description: str
    application_id: UUID | None = Field(default=None, alias="applicationId")
    application_title: str | None = Field(default=None, alias="applicationTitle")
    transfer_id: UUID | None = Field(default=None, alias="transferId")
    # `actor` is the principal `sub`, the raw identity for the audit log.
    # `actorName` is the display name the server resolves. Never show the raw
    # id in the UI.
    actor: str | None = None
    actor_name: str | None = Field(default=None, alias="actorName")
    invoice_date: date | None = Field(default=None, alias="invoiceDate")
    payment_date: date | None = Field(default=None, alias="paymentDate")
    correspondent: str | None = None
    note: str | None = None
    reference_number: str | None = Field(default=None, alias="referenceNumber")
    payment_method: PaymentMethod | None = Field(default=None, alias="paymentMethod")
    category: str | None = None
    invoice_id: UUID | None = Field(default=None, alias="invoiceId")
    invoice_number: str | None = Field(default=None, alias="invoiceNumber")
    # A set `parentExpenseId` means this booking IS a sub-booking. A
    # `childCount` above 0 means the booking HAS sub-bookings. The UI can
    # expand them. The `amount` is then the sum of the children and read-only.
    parent_expense_id: UUID | None = Field(default=None, alias="parentExpenseId")
    child_count: int = Field(default=0, alias="childCount")
    created_at: datetime = Field(alias="createdAt")


InvoiceStatus = Literal["open", "paid"]


class InvoiceCreate(_CamelModel):
    """Create an invoice.

    `grossAmount` is required. Every other field is optional.
    """

    number: str | None = None
    issue_date: date | None = Field(default=None, alias="issueDate")
    due_date: date | None = Field(default=None, alias="dueDate")
    supplier: str | None = None
    net_amount: Decimal | None = Field(default=None, alias="netAmount", ge=0, le=_MAX_AMOUNT)
    tax_amount: Decimal | None = Field(default=None, alias="taxAmount", ge=0, le=_MAX_AMOUNT)
    gross_amount: Decimal = Field(alias="grossAmount", ge=0, le=_MAX_AMOUNT)
    note: str | None = None
    status: InvoiceStatus = "open"
    # Optional receipt from the ZUGFeRD import. The token is a handle to the
    # original PDF already stored in MinIO. `/invoices/parse` returns it.
    file_token: str | None = Field(default=None, alias="fileToken")
    file_name: str | None = Field(default=None, alias="fileName")
    file_mime: str | None = Field(default=None, alias="fileMime")


class InvoiceParseResult(_CamelModel):
    """Result of `POST /invoices/parse`.

    The result holds the parsed header data and a handle to the stored original
    PDF. The UI pre-fills the entry dialog. On confirm the UI passes
    `fileToken` back to `POST /invoices`.
    """

    number: str | None = None
    issue_date: date | None = Field(default=None, alias="issueDate")
    due_date: date | None = Field(default=None, alias="dueDate")
    supplier: str | None = None
    net_amount: Decimal | None = Field(default=None, alias="netAmount")
    tax_amount: Decimal | None = Field(default=None, alias="taxAmount")
    gross_amount: Decimal = Field(alias="grossAmount")
    currency: str = "EUR"
    file_token: str = Field(alias="fileToken")
    file_name: str = Field(alias="fileName")
    file_mime: str = Field(alias="fileMime")
    # Possible duplicate: an invoice with the same number already exists. The
    # UI warns before the confirm but does not block the import.
    duplicate: bool = False


class InvoiceFileResult(_CamelModel):
    """Result of `POST /invoices/file`.

    The result is a handle to the original PDF the server just stored. It also
    covers a receipt that is not ZUGFeRD. The client passes it back to
    `POST /invoices` like `InvoiceParseResult.fileToken`.
    """

    file_token: str = Field(alias="fileToken")
    file_name: str = Field(alias="fileName")
    file_mime: str = Field(alias="fileMime")


class InvoiceUpdate(_CamelModel):
    """Partially update an invoice.

    The server writes the set fields only.
    """

    number: str | None = None
    issue_date: date | None = Field(default=None, alias="issueDate")
    due_date: date | None = Field(default=None, alias="dueDate")
    supplier: str | None = None
    net_amount: Decimal | None = Field(default=None, alias="netAmount", ge=0, le=_MAX_AMOUNT)
    tax_amount: Decimal | None = Field(default=None, alias="taxAmount", ge=0, le=_MAX_AMOUNT)
    gross_amount: Decimal | None = Field(default=None, alias="grossAmount", ge=0, le=_MAX_AMOUNT)
    note: str | None = None
    status: InvoiceStatus | None = None

    @model_validator(mode="after")
    def _at_least_one(self) -> InvoiceUpdate:
        if not self.model_fields_set:
            raise ValueError("at least one field required")
        return self


class InvoiceOut(_CamelModel):
    """Invoice base data plus the file flag."""

    id: UUID
    number: str | None = None
    issue_date: date | None = Field(default=None, alias="issueDate")
    due_date: date | None = Field(default=None, alias="dueDate")
    supplier: str | None = None
    net_amount: Decimal | None = Field(default=None, alias="netAmount")
    tax_amount: Decimal | None = Field(default=None, alias="taxAmount")
    gross_amount: Decimal = Field(alias="grossAmount")
    currency: str
    note: str | None = None
    status: InvoiceStatus = "open"
    file_name: str | None = Field(default=None, alias="fileName")
    has_file: bool = Field(default=False, alias="hasFile")
    actor: str | None = None
    created_at: datetime = Field(alias="createdAt")


class TransferCreate(_CamelModel):
    """Transfer from one cost center to another in the same fiscal year.

    The service creates an expense on `fromBudgetId` and an income on
    `toBudgetId` with the same amount and fiscal year. A `transferId` links
    both bookings.
    """

    from_budget_id: UUID = Field(alias="fromBudgetId")
    to_budget_id: UUID = Field(alias="toBudgetId")
    fiscal_year_id: UUID = Field(alias="fiscalYearId")
    amount: Decimal = Field(gt=0, le=_MAX_AMOUNT, allow_inf_nan=False)
    description: str = Field(min_length=1)

    @model_validator(mode="after")
    def _distinct(self) -> TransferCreate:
        if self.from_budget_id == self.to_budget_id:
            raise ValueError("from and to cost centre must differ")
        return self


class TransferOut(_CamelModel):
    """Result of a transfer with both booking ids."""

    transfer_id: UUID = Field(alias="transferId")
    expense_id: UUID = Field(alias="expenseId")
    income_id: UUID = Field(alias="incomeId")


class TransferUpdate(_CamelModel):
    """Update both legs of a transfer at once.

    `fromBudgetId` and `toBudgetId` are accepted only to repeat the current
    pair, so a round-trip of the read model works; a different value gives 409.
    """

    amount: Decimal | None = Field(default=None, gt=0, le=_MAX_AMOUNT, allow_inf_nan=False)
    description: str | None = Field(default=None, min_length=1)
    note: str | None = Field(default=None)
    invoice_date: date | None = Field(default=None, alias="invoiceDate")
    payment_date: date | None = Field(default=None, alias="paymentDate")
    from_budget_id: UUID | None = Field(default=None, alias="fromBudgetId")
    to_budget_id: UUID | None = Field(default=None, alias="toBudgetId")

    @model_validator(mode="after")
    def _at_least_one(self) -> TransferUpdate:
        if not self.model_fields_set:
            raise ValueError("at least one field required")
        return self


class TransferRowOut(_CamelModel):
    """One transfer as a single row, assembled from its two bookings."""

    transfer_id: UUID = Field(alias="transferId")
    expense_id: UUID = Field(alias="expenseId")
    income_id: UUID = Field(alias="incomeId")
    from_budget_id: UUID = Field(alias="fromBudgetId")
    from_path_key: str | None = Field(default=None, alias="fromPathKey")
    to_budget_id: UUID = Field(alias="toBudgetId")
    to_path_key: str | None = Field(default=None, alias="toPathKey")
    fiscal_year_id: UUID = Field(alias="fiscalYearId")
    amount: Decimal
    currency: str
    description: str
    note: str | None = None
    invoice_date: date | None = Field(default=None, alias="invoiceDate")
    payment_date: date | None = Field(default=None, alias="paymentDate")
    # `actor` is the raw principal `sub`; show `actorName` in the UI.
    actor: str | None = None
    actor_name: str | None = Field(default=None, alias="actorName")
    created_at: datetime = Field(alias="createdAt")


BudgetTreeNodeOut.model_rebuild()

__all__ = [
    "TransferCreate",
    "TransferOut",
    "BudgetApplicationOut",
    "AllocationOut",
    "AllocationSet",
    "AllocationView",
    "AssignBudgetOut",
    "AssignBudgetRequest",
    "BudgetNodeCreate",
    "BudgetNodeOut",
    "BudgetNodeUpdate",
    "BudgetTreeNodeOut",
    "ExpenseCreate",
    "ExpenseKind",
    "ExpenseOut",
    "ExpenseUpdate",
    "FiscalYearCreate",
    "FiscalYearOut",
    "FiscalYearUpdate",
    "MoveFiscalYearRequest",
]
