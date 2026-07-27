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
    # No `accountId` here. The account is not a manual booking field. Only the
    # bank reconciliation sets it.
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

    The sub-booking inherits the account, the cost center, the fiscal year and
    the kind from the parent. This schema carries the own values only: amount,
    description and metadata.
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
    account_id: UUID | None = Field(default=None, alias="accountId")
    account_name: str | None = Field(default=None, alias="accountName")
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


class AccountCreate(_CamelModel):
    """Create an account from a name and an IBAN as free text.

    An account is not bound to a cost center. The FinTS bank connection
    (`fintsEndpoint` and `fintsBlz`) is optional, and all bookers share it.
    Each booker sets the personal credentials (login and PIN) in the booking
    tab, not here.
    """

    name: str = Field(min_length=1, max_length=200)
    iban: str = Field(default="", max_length=64)
    active: bool = True
    fints_endpoint: str | None = Field(default=None, alias="fintsEndpoint", max_length=500)
    fints_blz: str | None = Field(default=None, alias="fintsBlz", max_length=20)


class AccountUpdate(_CamelModel):
    """Partially update an account.

    For a FinTS connection field, `null` or an empty string clears the value. A
    set value overwrites it. The login and the PIN are not part of the account
    data.
    """

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
    """Account base data with the FinTS bank connection (endpoint and BLZ).

    `fintsConfigured` means the connection is complete and the account is
    FinTS-capable. A personal login or PIN never appears here.
    """

    id: UUID
    name: str
    iban: str
    active: bool
    fints_endpoint: str | None = Field(default=None, alias="fintsEndpoint")
    fints_blz: str | None = Field(default=None, alias="fintsBlz")
    # True once the endpoint and the BLZ are present. The account is then
    # FinTS-syncable, as soon as a booker stores personal credentials.
    fints_configured: bool = Field(default=False, alias="fintsConfigured")
    # Last known bank balance and its as-of time. Null means never synced.
    fints_last_balance: Decimal | None = Field(default=None, alias="fintsLastBalance")
    fints_balance_at: datetime | None = Field(default=None, alias="fintsBalanceAt")


class AccountOption(_CamelModel):
    """Minimal account choice for booking dropdowns: id and name, NO IBAN.

    A booker without the account-data permission can read this. `fintsConfigured`
    is not a secret and means the account is FinTS-capable.
    `fintsHasCredential` means the requesting booker already stored own
    credentials. Without them the booker must connect on the first sync.
    """

    id: UUID
    name: str
    fints_configured: bool = Field(default=False, alias="fintsConfigured")
    fints_has_credential: bool = Field(default=False, alias="fintsHasCredential")
    fints_last_sync_at: datetime | None = Field(default=None, alias="fintsLastSyncAt")
    # Last bank balance and its as-of time for the accounts tab.
    fints_last_balance: Decimal | None = Field(default=None, alias="fintsLastBalance")
    fints_balance_at: datetime | None = Field(default=None, alias="fintsBalanceAt")


class FintsCredentialIn(_CamelModel):
    """Personal FinTS credentials of the booker for an account.

    `fintsPin` is write-only. The server stores it encrypted and never returns
    it. The booker sets the credentials on the first connect in the booking
    tab and replaces them on a change.
    """

    fints_login: str = Field(alias="fintsLogin", min_length=1, max_length=200)
    fints_pin: str = Field(alias="fintsPin", min_length=1, max_length=200)


class FintsCredentialStatus(_CamelModel):
    """Connection status of a booker for an account.

    `configured` means the account is FinTS-capable, so the endpoint and the
    BLZ are set. `hasCredential` means the requesting booker stored own
    credentials. `login` is the username of that booker and is not a secret.
    The PIN never appears.
    """

    configured: bool = False
    has_credential: bool = Field(default=False, alias="hasCredential")
    fints_login: str | None = Field(default=None, alias="fintsLogin")
    fints_last_sync_at: datetime | None = Field(default=None, alias="fintsLastSyncAt")
    # Cooldown after a bank lock or a signature rejection. The server refuses a
    # sync until this time. The UI disables the fetch button and warns against
    # a retry.
    fints_locked_until: datetime | None = Field(default=None, alias="fintsLockedUntil")


BankLineState = Literal["unmatched", "suggested", "matched", "ignored"]
BankSyncStatus = Literal["done", "needs_tan"]


class StatementLineOut(_CamelModel):
    """Staged bank transaction.

    `amount` is signed: above 0 is an inflow and below 0 is an outflow. `kind`
    is the booking kind derived from that sign.
    """

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
    # Booking of a `matched` line, taken from `bank_allocation`. A split payment
    # uses the oldest one. This is the deep-link target for "view booking"
    # (#expenses-ux).
    matched_expense_id: UUID | None = Field(default=None, alias="matchedExpenseId")
    created_at: datetime = Field(alias="createdAt")


class StatementLineDetail(StatementLineOut):
    """Detail view of a staged line.

    The detail adds the raw parser payload with the source-format fields and
    the batch metadata, plus the idempotency key. Both help to diagnose the
    import and the dedup behavior. The read permission is the same as for the
    list.
    """

    raw_payload: dict = Field(default_factory=dict, alias="rawPayload")
    idempotency_key: str = Field(alias="idempotencyKey")


class BankSyncResult(_CamelModel):
    """Result of one FinTS sync step.

    `status='done'` sets `imported` and `duplicates`. `status='needs_tan'` sets
    `sessionToken` and `challenge` to signal that the bank wants a TAN. For a
    `decoupled` challenge the booker approves in the banking app. The client
    then polls `POST .../tan` without a code.
    """

    status: BankSyncStatus
    account_id: UUID = Field(alias="accountId")
    imported: int = 0
    duplicates: int = 0
    # The fields below are set for `status='needs_tan'` only.
    session_token: UUID | None = Field(default=None, alias="sessionToken")
    challenge: str | None = None
    challenge_html: str | None = Field(default=None, alias="challengeHtml")
    # Optical challenge (photoTAN or QR-TAN) as a data URL for direct display.
    challenge_image: str | None = Field(default=None, alias="challengeImage")
    decoupled: bool = False


class BankTanRequest(_CamelModel):
    """TAN to resume a pending sync session.

    Leave the field empty for a decoupled pushTAN. The call is then a pure poll
    that asks whether the booker approved in the app.
    """

    tan: str = Field(default="", max_length=100)


class BankImportResult(_CamelModel):
    """Result of a file import (CAMT.053 or MT940)."""

    account_id: UUID = Field(alias="accountId")
    imported: int = 0
    duplicates: int = 0


class ConfirmLineRequest(_CamelModel):
    """Confirm a transaction into a booking.

    Give either `matchExpenseId` to attach the line to an EXISTING booking or
    `budgetId` to create a new booking against that cost center. The sign of
    the amount then sets the kind. `fiscalYearId` is optional. Without it the
    server takes the single active fiscal year. `description` overrides the
    default, which is the purpose text.
    """

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
    """Ignore a staged transaction.

    `reason` is optional free text. The platform keeps it in the audit log
    (bank_line_ignore) only and does not store it on the line.
    """

    reason: str | None = Field(default=None, max_length=500)


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
    "StatementLineDetail",
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
