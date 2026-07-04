"""API schemas of the budget tree.

camelCase aliases via :class:`_CamelModel`; money as ``Decimal``
(numeric(12,2)); dates as ``date``. ``pathKey`` is server-maintained — not
accepted in requests, out DTOs only.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.modules.budget.schemas import _CamelModel

# Money cap = DB column ``numeric(12, 2)``. Applied as ``le`` on input fields so
# an oversized amount yields a clean 422 instead of a numeric-overflow 500.
_MAX_AMOUNT = Decimal("9999999999.99")


# --------------------------------------------------------------------- nodes
class BudgetNodeCreate(_CamelModel):
    """Create a cost centre. ``parentId=null`` = top level (``gremiumId`` required).

    ``fiscalStartMonth``/``fiscalStartDay`` = fiscal cutoff (top-level only;
    default Jan 1)."""

    key: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    parent_id: UUID | None = Field(default=None, alias="parentId")
    gremium_id: UUID | None = Field(default=None, alias="gremiumId")
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    active: bool = True
    color: str | None = None
    fiscal_start_month: int = Field(default=1, ge=1, le=12, alias="fiscalStartMonth")
    # 1..28: the cutoff must exist in EVERY month; days 29-31 would raise a
    # ``date(...)`` ValueError -> 500 that leaves the budget unusable.
    fiscal_start_day: int = Field(default=1, ge=1, le=28, alias="fiscalStartDay")


class BudgetNodeUpdate(_CamelModel):
    """Partially update a cost centre (key/parent immutable for path stability).

    ``None`` = unchanged. ``color=""`` clears the color. ``acceptedStateKeys``/
    ``deniedStateKeys``/``fiscalStart*`` only make sense at the top level."""

    key: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    active: bool | None = None
    color: str | None = None
    accepted_state_keys: list[str] | None = Field(default=None, alias="acceptedStateKeys")
    denied_state_keys: list[str] | None = Field(default=None, alias="deniedStateKeys")
    hidden_in_budget: bool | None = Field(default=None, alias="hiddenInBudget")
    # Visibility gremium — ``None`` in the payload clears the assignment.
    view_gremium_id: UUID | None = Field(default=None, alias="viewGremiumId")
    fiscal_start_month: int | None = Field(default=None, ge=1, le=12, alias="fiscalStartMonth")
    # 1..28: see ``BudgetNodeCreate`` — the cutoff must exist in every month.
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

    ``committed`` = ``bound + expended`` (total consumption, backward compat).
    ``available = allocated - bound - expended + income``.
    """

    fiscal_year_id: UUID = Field(alias="fiscalYearId")
    allocated: Decimal
    # Bound: accepted applications, reduced pro rata by expenses bound to them.
    bound: Decimal = Decimal("0")
    # Expended: actual expenses (kind='expense').
    expended: Decimal = Decimal("0")
    # Income (kind='income') — raises the available budget.
    income: Decimal = Decimal("0")
    committed: Decimal
    requested: Decimal = Decimal("0")
    available: Decimal


class BudgetTreeNodeOut(_CamelModel):
    """Tree node + per-fiscal-year sums + children (recursive) — ``GET /budgets``."""

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


# ---------------------------------------------------------------- fiscal years
class FiscalYearCreate(_CamelModel):
    """Create a fiscal year — the year only (start/end derive from the budget cutoff)."""

    year: int = Field(ge=1900, le=2200)
    active: bool = True


class FiscalYearUpdate(_CamelModel):
    """Update a fiscal year (year and/or active flag; disjointness re-checked)."""

    year: int | None = Field(default=None, ge=1900, le=2200)
    active: bool | None = None


class FiscalYearOut(_CamelModel):
    """Fiscal-year base data. ``display`` = ``YYYY`` (Jan-1 cutoff) or ``YYYY/YY``."""

    id: UUID
    budget_id: UUID = Field(alias="budgetId")
    year: int
    display: str
    start_date: date = Field(alias="startDate")
    end_date: date = Field(alias="endDate")
    active: bool


# ----------------------------------------------------------------- allocation
class AllocationSet(_CamelModel):
    """Set the top-down allocation (``PUT .../allocations/{fiscalYearId}``)."""

    allocated: Decimal = Field(ge=0, allow_inf_nan=False)


class AllocationOut(_CamelModel):
    """Result of an allocation."""

    budget_id: UUID = Field(alias="budgetId")
    fiscal_year_id: UUID = Field(alias="fiscalYearId")
    allocated: Decimal


# ------------------------------------------------------------------- assign
class AssignBudgetRequest(_CamelModel):
    """Assign an application to a cost centre; also sets the fiscal year.

    ``budgetId=null`` clears the assignment (``fiscalYearId`` -> null too).
    ``fiscalYearId`` is optional: if set, it must belong to the cost centre's
    top budget; if omitted, the service derives the single active fiscal year
    or requires an explicit choice (422 — as with expenses).
    """

    budget_id: UUID | None = Field(default=None, alias="budgetId")
    fiscal_year_id: UUID | None = Field(default=None, alias="fiscalYearId")


class MoveFiscalYearRequest(_CamelModel):
    """Move an application to another fiscal year (of the top budget)."""

    fiscal_year_id: UUID = Field(alias="fiscalYearId")


class AssignBudgetOut(_CamelModel):
    """Result of a cost-centre/fiscal-year assignment."""

    application_id: UUID = Field(alias="applicationId")
    budget_id: UUID | None = Field(alias="budgetId")
    fiscal_year_id: UUID | None = Field(alias="fiscalYearId")


class BudgetApplicationOut(_CamelModel):
    """Application in a cost centre (+ subtree) — for the budget drilldown list.

    Money as ``Decimal``; ``stage`` from the ``budget_entry`` (or None)."""

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


# ------------------------------------------------------------------- expense
ExpenseKind = Literal["expense", "income"]
# Payment method: bank transfer | cash | direct debit | card | PayPal.
PaymentMethod = Literal["ueberweisung", "bar", "lastschrift", "karte", "paypal"]


class ExpenseCreate(_CamelModel):
    """Book an expense/income against a cost centre + fiscal year, optionally app-bound.

    ``budgetId`` is required for standalone bookings; for bound ones the cost
    centre is inherited from the application and ``budgetId``/``fiscalYearId``
    are ignored. ``applicationId`` binds the booking (replaces its binding pro
    rata), allowed for ``kind='expense'`` only. ``fiscalYearId`` is optional
    for standalone expenses: if missing, the single active fiscal year of the
    top budget is chosen (ambiguous/none -> 422).
    """

    amount: Decimal = Field(gt=0, le=_MAX_AMOUNT, allow_inf_nan=False)
    description: str = Field(min_length=1)
    kind: ExpenseKind = "expense"
    budget_id: UUID | None = Field(default=None, alias="budgetId")
    fiscal_year_id: UUID | None = Field(default=None, alias="fiscalYearId")
    application_id: UUID | None = Field(default=None, alias="applicationId")
    # No ``accountId``: the account is not a manual booking field, only bank
    # reconciliation sets it.
    # Optional metadata.
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
    """Create a sub-booking manually: account/cost centre/fiscal year/kind are
    inherited from the parent — only own values here (amount, description, metadata)."""

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
    """Update a booked expense/income. Amount, description, cost centre and the
    optional metadata are editable; fiscal year and application binding stay
    fixed (booking stability). Only set fields are written; explicit ``null``
    clears an optional field (except ``budgetId`` — required FK)."""

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
    """Booked expense/income (base data)."""

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
    account_id: UUID | None = Field(default=None, alias="accountId")
    account_name: str | None = Field(default=None, alias="accountName")
    transfer_id: UUID | None = Field(default=None, alias="transferId")
    # ``actor`` = principal ``sub`` (raw identity, audit). ``actorName`` is the
    # server-resolved display name — never show the raw id in the UI.
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
    # Sub-bookings: ``parentExpenseId`` set -> this booking IS a sub-booking.
    # ``childCount`` > 0 -> the booking HAS sub-bookings (expandable; its
    # ``amount`` = sum of the children and is then read-only).
    parent_expense_id: UUID | None = Field(default=None, alias="parentExpenseId")
    child_count: int = Field(default=0, alias="childCount")
    created_at: datetime = Field(alias="createdAt")


# -------------------------------------------------------------------- invoices
InvoiceStatus = Literal["open", "paid"]


class InvoiceCreate(_CamelModel):
    """Create an invoice. ``grossAmount`` required; everything else optional."""

    number: str | None = None
    issue_date: date | None = Field(default=None, alias="issueDate")
    due_date: date | None = Field(default=None, alias="dueDate")
    supplier: str | None = None
    net_amount: Decimal | None = Field(default=None, alias="netAmount", ge=0, le=_MAX_AMOUNT)
    tax_amount: Decimal | None = Field(default=None, alias="taxAmount", ge=0, le=_MAX_AMOUNT)
    gross_amount: Decimal = Field(alias="grossAmount", ge=0, le=_MAX_AMOUNT)
    note: str | None = None
    status: InvoiceStatus = "open"
    # Optional receipt from the ZUGFeRD import: handle to the original PDF
    # already stored in MinIO (``/invoices/parse`` returns the token).
    file_token: str | None = Field(default=None, alias="fileToken")
    file_name: str | None = Field(default=None, alias="fileName")
    file_mime: str | None = Field(default=None, alias="fileMime")


class InvoiceParseResult(_CamelModel):
    """Result of ``POST /invoices/parse``: parsed header data + handle to the
    stored original PDF. The UI pre-fills the entry dialog; ``fileToken`` is
    passed back to ``POST /invoices`` on confirm."""

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
    # UI warns before confirming but does not block the import.
    duplicate: bool = False


class InvoiceFileResult(_CamelModel):
    """Result of ``POST /invoices/file``: handle to the just-stored original
    PDF — also for non-ZUGFeRD receipts. Passed back to ``POST /invoices`` like
    ``InvoiceParseResult.fileToken``."""

    file_token: str = Field(alias="fileToken")
    file_name: str = Field(alias="fileName")
    file_mime: str = Field(alias="fileMime")


class InvoiceUpdate(_CamelModel):
    """Partially update an invoice. Only set fields are written."""

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
    """Invoice (base data + file flag)."""

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


# -------------------------------------------------------------------- accounts
class AccountCreate(_CamelModel):
    """Create an account — name + IBAN (free text). Not bound to cost centres.

    The FinTS bank connection (``fintsEndpoint`` + ``fintsBlz``) is optional and
    shared by all bookers. Personal credentials (login/PIN) are set by each
    booker in the booking tab, not here."""

    name: str = Field(min_length=1, max_length=200)
    iban: str = Field(default="", max_length=64)
    active: bool = True
    fints_endpoint: str | None = Field(default=None, alias="fintsEndpoint", max_length=500)
    fints_blz: str | None = Field(default=None, alias="fintsBlz", max_length=20)


class AccountUpdate(_CamelModel):
    """Partially update an account. FinTS connection fields: ``null``/``""``
    clears, a set value overwrites (login/PIN are not part of account data)."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    iban: str | None = Field(default=None, max_length=64)
    active: bool | None = None
    fints_endpoint: str | None = Field(default=None, alias="fintsEndpoint", max_length=500)
    fints_blz: str | None = Field(default=None, alias="fintsBlz", max_length=20)

    @model_validator(mode="after")
    def _at_least_one(self) -> AccountUpdate:
        if not self.model_fields_set:
            raise ValueError("at least one field required")
        return self


class AccountOut(_CamelModel):
    """Account base data incl. FinTS bank connection (endpoint + BLZ).

    ``fintsConfigured`` = connection complete (account is FinTS-capable);
    personal logins/PINs never appear here."""

    id: UUID
    name: str
    iban: str
    active: bool
    fints_endpoint: str | None = Field(default=None, alias="fintsEndpoint")
    fints_blz: str | None = Field(default=None, alias="fintsBlz")
    # True once endpoint + BLZ are present: the account is FinTS-syncable (as
    # soon as a booker stores personal credentials).
    fints_configured: bool = Field(default=False, alias="fintsConfigured")
    # Last known bank balance + as-of time; null = never synced.
    fints_last_balance: Decimal | None = Field(default=None, alias="fintsLastBalance")
    fints_balance_at: datetime | None = Field(default=None, alias="fintsBalanceAt")


class AccountOption(_CamelModel):
    """Minimal account choice (id + name, NO IBAN) for booking dropdowns —
    readable for bookers without account-data rights.

    ``fintsConfigured`` (not a secret) = account is FinTS-capable;
    ``fintsHasCredential`` = the requesting booker already stored own
    credentials — otherwise they must connect on first sync."""

    id: UUID
    name: str
    fints_configured: bool = Field(default=False, alias="fintsConfigured")
    fints_has_credential: bool = Field(default=False, alias="fintsHasCredential")
    fints_last_sync_at: datetime | None = Field(default=None, alias="fintsLastSyncAt")
    # Last bank balance + as-of time for the accounts tab.
    fints_last_balance: Decimal | None = Field(default=None, alias="fintsLastBalance")
    fints_balance_at: datetime | None = Field(default=None, alias="fintsBalanceAt")


class FintsCredentialIn(_CamelModel):
    """Personal FinTS credentials of the booker for an account.

    ``fintsPin`` is write-only (stored encrypted, never returned). Set on first
    connect in the booking tab, replaced on change."""

    fints_login: str = Field(alias="fintsLogin", min_length=1, max_length=200)
    fints_pin: str = Field(alias="fintsPin", min_length=1, max_length=200)


class FintsCredentialStatus(_CamelModel):
    """Connection status of a booker for an account.

    ``configured`` = account is FinTS-capable (endpoint + BLZ). ``hasCredential``
    = the requesting booker stored own credentials; ``login`` is their username
    (not a secret), the PIN never appears."""

    configured: bool = False
    has_credential: bool = Field(default=False, alias="hasCredential")
    fints_login: str | None = Field(default=None, alias="fintsLogin")
    fints_last_sync_at: datetime | None = Field(default=None, alias="fintsLastSyncAt")
    # Cooldown after a bank lock/signature rejection: the server refuses syncs
    # until then; the UI disables the fetch button and warns against retries.
    fints_locked_until: datetime | None = Field(default=None, alias="fintsLockedUntil")


# ------------------------------------------------------- bank statement
BankLineState = Literal["unmatched", "suggested", "matched", "ignored"]
BankSyncStatus = Literal["done", "needs_tan"]


class StatementLineOut(_CamelModel):
    """Staged bank transaction. ``amount`` is signed (> 0 inflow, < 0 outflow);
    ``kind`` is the booking kind derived from it."""

    id: UUID
    account_id: UUID = Field(alias="accountId")
    amount: Decimal
    kind: ExpenseKind
    currency: str
    booking_date: date | None = Field(default=None, alias="bookingDate")
    value_date: date | None = Field(default=None, alias="valueDate")
    purpose: str | None = None
    counterparty_name: str | None = Field(default=None, alias="counterpartyName")
    counterparty_iban: str | None = Field(default=None, alias="counterpartyIban")
    end_to_end_id: str | None = Field(default=None, alias="endToEndId")
    reference: str | None = None
    match_state: BankLineState = Field(alias="matchState")
    suggested_budget_id: UUID | None = Field(default=None, alias="suggestedBudgetId")
    suggested_path_key: str | None = Field(default=None, alias="suggestedPathKey")
    suggested_expense_id: UUID | None = Field(default=None, alias="suggestedExpenseId")
    # Booking of a ``matched`` line (from ``bank_allocation``; the oldest one for
    # split payments) — deep-link target for "view booking" (#expenses-ux).
    matched_expense_id: UUID | None = Field(default=None, alias="matchedExpenseId")
    created_at: datetime = Field(alias="createdAt")


class BankSyncResult(_CamelModel):
    """Result of one FinTS sync step.

    ``status='done'`` -> ``imported``/``duplicates`` set. ``status='needs_tan'``
    -> ``sessionToken`` + ``challenge`` signal a TAN is needed (for
    ``decoupled``, approving in the banking app + polling ``POST .../tan``
    without a code suffices)."""

    status: BankSyncStatus
    account_id: UUID = Field(alias="accountId")
    imported: int = 0
    duplicates: int = 0
    # needs_tan:
    session_token: UUID | None = Field(default=None, alias="sessionToken")
    challenge: str | None = None
    challenge_html: str | None = Field(default=None, alias="challengeHtml")
    # Optical challenge (photoTAN/QR-TAN) as a data URL for direct display.
    challenge_image: str | None = Field(default=None, alias="challengeImage")
    decoupled: bool = False


class BankTanRequest(_CamelModel):
    """TAN to resume a pending sync session. Leave empty for decoupled pushTAN
    (pure poll: "approved in the app?")."""

    tan: str = Field(default="", max_length=100)


class BankImportResult(_CamelModel):
    """Result of a file import (CAMT.053/MT940)."""

    account_id: UUID = Field(alias="accountId")
    imported: int = 0
    duplicates: int = 0


class ConfirmLineRequest(_CamelModel):
    """Confirm a transaction into a booking.

    Either ``matchExpenseId`` (attach to an EXISTING booking) or ``budgetId``
    (create a new booking against that cost centre — kind from the sign).
    ``fiscalYearId`` optional (else the single active fiscal year);
    ``description`` overrides the default (purpose text)."""

    budget_id: UUID | None = Field(default=None, alias="budgetId")
    fiscal_year_id: UUID | None = Field(default=None, alias="fiscalYearId")
    match_expense_id: UUID | None = Field(default=None, alias="matchExpenseId")
    description: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _target_required(self) -> ConfirmLineRequest:
        if self.budget_id is None and self.match_expense_id is None:
            raise ValueError("either budgetId or matchExpenseId is required")
        if self.budget_id is not None and self.match_expense_id is not None:
            raise ValueError("budgetId and matchExpenseId are mutually exclusive")
        return self


class IgnoreLineRequest(_CamelModel):
    """Ignore a staged transaction. ``reason`` is optional free text kept in the
    audit log (bank_line_ignore) only — not stored on the line."""

    reason: str | None = Field(default=None, max_length=500)


# ------------------------------------------------------------------- transfer
class TransferCreate(_CamelModel):
    """Transfer cost centre -> cost centre (same fiscal year).

    Creates an expense on ``fromBudgetId`` and an income on ``toBudgetId``
    (same amount/fiscal year), linked via a ``transferId``."""

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
    """Result of a transfer (both booking ids)."""

    transfer_id: UUID = Field(alias="transferId")
    expense_id: UUID = Field(alias="expenseId")
    income_id: UUID = Field(alias="incomeId")


BudgetTreeNodeOut.model_rebuild()

__all__ = [
    "AccountCreate",
    "AccountOption",
    "AccountOut",
    "AccountUpdate",
    "BankImportResult",
    "BankLineState",
    "BankSyncResult",
    "BankSyncStatus",
    "BankTanRequest",
    "ConfirmLineRequest",
    "FintsCredentialIn",
    "FintsCredentialStatus",
    "StatementLineOut",
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
