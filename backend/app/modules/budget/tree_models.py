"""Hierarchical budgets / cost centres plus fiscal years.

:class:`Budget` is a tree node (``parent_id`` self-FK; ``path_key`` composed
like ``VS-800-04``, maintained by the service). :class:`FiscalYear` belongs to
a top-level budget (service check). :class:`BudgetAllocation` is the top-down
allocation ``Budget x FiscalYear`` — available = allocated, NO roll-up;
consumption rolls up from approved applications (not persisted;
``tree_rules.rollup_committed``). Single currency EUR (CHECK).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CHAR,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, CreatedAtMixin, UUIDPkMixin


class Budget(UUIDPkMixin, CreatedAtMixin, Base):
    """Cost-centre node; ``parent_id`` NULL = top level.

    ``gremium_id`` is set only at the top level (children inherit logically);
    ``key`` is the path segment, ``path_key`` the composed key (``VS-800-04``).
    Self-FK ``ON DELETE RESTRICT`` — children must be deleted first.
    """

    __tablename__ = "budget"

    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("budget.id", ondelete="RESTRICT"), nullable=True
    )
    gremium_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("gremium.id", ondelete="CASCADE"), nullable=True
    )
    key: Mapped[str] = mapped_column(Text)
    path_key: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    currency: Mapped[str] = mapped_column(CHAR(3), server_default="EUR")
    active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    # Display color for pies and tree; NULL = auto.
    color: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Top-level only: flow-state keys counted as accepted (-> committed) or
    # denied (-> excluded); everything else counts as requested.
    accepted_state_keys: Mapped[list] = mapped_column(JSONB, server_default="[]")
    denied_state_keys: Mapped[list] = mapped_column(JSONB, server_default="[]")
    # Hide in the budget tab: display-only — values still count in parent
    # rollups/export. Python default in addition to the server default so
    # freshly constructed instances carry a bool before flush.
    hidden_in_budget: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    # Visibility gremium: its members see this cost centre (+ subtree) as a root
    # in the budget tab without a global budget.* permission. Independent of the
    # top-level ``gremium_id`` classification.
    view_gremium_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("gremium.id", ondelete="SET NULL"), nullable=True
    )
    # Fiscal-year cutoff (day/month of period start) — top-level only. Default
    # Jan 1; a different cutoff renders fiscal years as "YYYY/YY". Fiscal years
    # store only the year; start/end derive from this cutoff.
    fiscal_start_month: Mapped[int] = mapped_column(SmallInteger, server_default="1")
    fiscal_start_day: Mapped[int] = mapped_column(SmallInteger, server_default="1")

    __table_args__ = (
        UniqueConstraint("parent_id", "key", name="uq_budget_parent_key"),
        UniqueConstraint("path_key", name="uq_budget_path_key"),
        CheckConstraint("currency = 'EUR'", name="budget_currency_eur"),
        CheckConstraint(
            "fiscal_start_month BETWEEN 1 AND 12", name="budget_fiscal_start_month"
        ),
        CheckConstraint(
            "fiscal_start_day BETWEEN 1 AND 31", name="budget_fiscal_start_day"
        ),
        Index("ix_budget_parent_id", "parent_id"),
        Index("ix_budget_gremium_id", "gremium_id"),
    )


class FiscalYear(UUIDPkMixin, CreatedAtMixin, Base):
    """Fiscal year per top-level budget, identified by ``year`` (start year).

    No free-text name. Start/end derive from the top budget's
    ``fiscal_start_month``/``fiscal_start_day`` (``start = cutoff(year)``,
    ``end = cutoff(year+1) - 1 day``) and are persisted for disjointness and
    filtering. Displayed as ``YYYY`` for a Jan-1 cutoff, else ``YYYY/YY``.
    """

    __tablename__ = "fiscal_year"

    budget_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("budget.id", ondelete="CASCADE")
    )
    year: Mapped[int] = mapped_column(Integer)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(Boolean, server_default="true")

    __table_args__ = (
        UniqueConstraint("budget_id", "year", name="uq_fiscal_year_budget_year"),
        CheckConstraint("end_date > start_date", name="fiscal_year_dates"),
        Index("ix_fiscal_year_budget_id", "budget_id"),
    )


class BudgetAllocation(UUIDPkMixin, CreatedAtMixin, Base):
    """Top-down allocation ``Budget x FiscalYear``.

    ``allocated`` = available sum of the cost centre in this fiscal year.
    Service invariant: sum of the direct children's ``allocated`` must not
    exceed the parent's (per fiscal year).
    """

    __tablename__ = "budget_allocation"

    budget_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("budget.id", ondelete="CASCADE")
    )
    fiscal_year_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fiscal_year.id", ondelete="CASCADE")
    )
    allocated: Mapped[Decimal] = mapped_column(Numeric(12, 2), server_default="0")

    __table_args__ = (
        UniqueConstraint(
            "budget_id", "fiscal_year_id", name="uq_budget_allocation_budget_fy"
        ),
        Index("ix_budget_allocation_fiscal_year_id", "fiscal_year_id"),
    )


class BudgetExpense(UUIDPkMixin, CreatedAtMixin, Base):
    """Actual expense or income booked against a cost centre + fiscal year.

    ``kind='expense'`` reduces the budget; ``kind='income'`` increases it.
    ``application_id`` (optional, NOT unique — multiple partial expenses per
    application): an application-bound expense replaces its committed amount
    pro rata (``bound(app) = max(0, amount - sum of bound expenses)``); cost
    centre + fiscal year are inherited from the application (service
    invariant). Income rows are always standalone (``application_id`` null).
    ``fiscal_year_id`` must belong to the node's top level (service check).
    """

    __tablename__ = "budget_expense"

    budget_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("budget.id", ondelete="CASCADE")
    )
    fiscal_year_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fiscal_year.id", ondelete="CASCADE")
    )
    # Booked against one application (replaces its binding pro rata) or
    # standalone (``None``). ``SET NULL`` on application delete keeps the
    # booking as a standalone expense.
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("application.id", ondelete="SET NULL"), nullable=True
    )
    # Optional account (bank account, freely managed; NOT bound to cost centres).
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("account.id", ondelete="SET NULL"), nullable=True
    )
    # Optional invoice: 1 invoice : N bookings. SET NULL on invoice delete keeps
    # the booking.
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("invoice.id", ondelete="SET NULL"), nullable=True
    )
    # Links the two bookings of a transfer (source expense <-> target income).
    transfer_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    # 'expense' | 'income'.
    kind: Mapped[str] = mapped_column(Text, server_default="expense")
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(CHAR(3), server_default="EUR")
    description: Mapped[str] = mapped_column(Text)
    actor: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Optional metadata:
    # Invoice and payment date (business dates, independent of created_at).
    invoice_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    payment_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Correspondent (free text): from whom (income) / for whom (expense).
    correspondent: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Notes (multi-line free text).
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Receipt/invoice reference (free text).
    reference_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Payment method: ueberweisung | bar | lastschrift | karte.
    payment_method: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Category/tag (free text) for grouping beyond the cost centre.
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Sub-booking: points at the parent booking. Children INHERIT
    # account/cost-centre/fiscal-year/kind from the parent (column values are
    # copied so rollups/queries apply) and carry only their own
    # amount/description/dates/receipt/bank link. The parent amount is the sum
    # of the children. Budget rollup counts parents only
    # (parent_expense_id IS NULL); children are pure breakdown. CASCADE:
    # deleting the parent deletes its children.
    parent_expense_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("budget_expense.id", ondelete="CASCADE"), nullable=True
    )

    __table_args__ = (
        CheckConstraint("amount > 0", name="budget_expense_amount_positive"),
        CheckConstraint("currency = 'EUR'", name="budget_expense_currency_eur"),
        CheckConstraint(
            "kind IN ('expense', 'income')", name="budget_expense_kind_valid"
        ),
        CheckConstraint(
            "payment_method IS NULL OR payment_method IN "
            "('ueberweisung', 'bar', 'lastschrift', 'karte', 'paypal')",
            name="budget_expense_payment_method_valid",
        ),
        Index("ix_budget_expense_budget_id", "budget_id"),
        Index("ix_budget_expense_fiscal_year_id", "fiscal_year_id"),
        Index("ix_budget_expense_application_id", "application_id"),
        Index("ix_budget_expense_account_id", "account_id"),
        Index("ix_budget_expense_transfer_id", "transfer_id"),
        Index("ix_budget_expense_invoice_date", "invoice_date"),
        Index("ix_budget_expense_invoice_id", "invoice_id"),
        Index("ix_budget_expense_parent_expense_id", "parent_expense_id"),
    )


class Account(UUIDPkMixin, CreatedAtMixin, Base):
    """Account (e.g. bank account) — freely managed, not bound to cost centres.

    Optional reference on bookings (which account moved). ``iban`` is free text
    (no format/checksum validation)."""

    __tablename__ = "account"

    name: Mapped[str] = mapped_column(Text)
    iban: Mapped[str] = mapped_column(Text, server_default="")
    active: Mapped[bool] = mapped_column(Boolean, server_default="true")

    # FinTS: only the bank connection (endpoint + BLZ) lives on the account —
    # shared by all bookers, set by the admin. Personal credentials live per
    # principal in :class:`AccountFintsCredential`; the SCA client state is
    # bound to user+device (shared state would break TAN/SCA). Without
    # ``fints_endpoint`` + ``fints_blz`` the account is not FinTS-capable.
    fints_endpoint: Mapped[str | None] = mapped_column(Text, nullable=True)
    fints_blz: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Last known account balance: from a sync's closing balance (HKSAL) or the
    # ``:62F:``/CLBD balance of a file import; ``fints_balance_at`` is its
    # as-of time. Display/reconcile value only — not part of budget math.
    fints_last_balance: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    fints_balance_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (Index("ix_account_name", "name"),)


class AccountFintsCredential(UUIDPkMixin, CreatedAtMixin, Base):
    """Personal FinTS credentials of one principal for one account.

    Bookers share the bank account but have individual online-banking logins,
    so login + PIN belong to the user, not the account. The PIN is stored
    encrypted only (Fernet, ``app.shared.crypto``) and never returned in
    plaintext. ``fints_state`` is the encrypted serialized FinTS client state
    (``system_id`` etc.) for the ~90-day SCA window — bound to user + device,
    hence separate per credential. Both FKs ``ON DELETE CASCADE``: deleting the
    account/principal removes the secret.
    """

    __tablename__ = "account_fints_credential"

    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("account.id", ondelete="CASCADE")
    )
    principal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("principal.id", ondelete="CASCADE")
    )
    fints_login: Mapped[str] = mapped_column(Text)
    fints_pin_encrypted: Mapped[str] = mapped_column(Text)
    fints_tan_mechanism: Mapped[str | None] = mapped_column(Text, nullable=True)
    fints_state: Mapped[str | None] = mapped_column(Text, nullable=True)
    fints_last_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Lock cooldown: set after a bank lock/signature rejection; the service
    # refuses syncs until then so retries don't worsen the bank-side lock.
    fints_locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "account_id", "principal_id", name="uq_account_fints_credential_owner"
        ),
        Index("ix_account_fints_credential_account_id", "account_id"),
        Index("ix_account_fints_credential_principal_id", "principal_id"),
    )


class BankStatementLine(UUIDPkMixin, CreatedAtMixin, Base):
    """Single bank transaction — staged before it becomes a booking.

    From a FinTS fetch or file import (CAMT.053/MT940). ``idempotency_key``
    makes re-imports idempotent (``ON CONFLICT DO NOTHING``). ``amount`` is
    signed (>0 inflow, <0 outflow); on confirm it becomes a ``budget_expense``
    with ``kind`` from the sign and ``amount = abs(...)`` (DB CHECK
    ``amount > 0``).
    """

    __tablename__ = "bank_statement_line"

    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("account.id", ondelete="CASCADE")
    )
    idempotency_key: Mapped[str] = mapped_column(Text)
    raw_payload: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    booking_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    value_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(CHAR(3), server_default="EUR")
    purpose: Mapped[str | None] = mapped_column(Text, nullable=True)
    counterparty_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    counterparty_iban: Mapped[str | None] = mapped_column(Text, nullable=True)
    end_to_end_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 'unmatched' | 'suggested' | 'matched' | 'ignored'.
    match_state: Mapped[str] = mapped_column(Text, server_default="unmatched")
    # Matcher suggestion (UI hint only; binding only on confirm).
    suggested_budget_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("budget.id", ondelete="SET NULL"), nullable=True
    )
    suggested_expense_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("budget_expense.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "account_id", "idempotency_key", name="uq_bank_statement_line_idem"
        ),
        CheckConstraint(
            "currency = 'EUR'", name="bank_statement_line_currency_eur"
        ),
        CheckConstraint(
            "match_state IN ('unmatched', 'suggested', 'matched', 'ignored')",
            name="bank_statement_line_state_valid",
        ),
        Index("ix_bank_statement_line_account_id", "account_id"),
        Index("ix_bank_statement_line_match_state", "match_state"),
        Index("ix_bank_statement_line_booking_date", "booking_date"),
    )


class BankAllocation(UUIDPkMixin, CreatedAtMixin, Base):
    """Bank line <-> booking link (N:M — partial/collective payments).

    A transaction can split across bookings, and a booking can be paid by
    several transactions. ``allocated_amount`` is the allocated partial amount
    (positive). CASCADE on both sides.
    """

    __tablename__ = "bank_allocation"

    statement_line_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bank_statement_line.id", ondelete="CASCADE")
    )
    expense_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("budget_expense.id", ondelete="CASCADE")
    )
    allocated_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))

    __table_args__ = (
        UniqueConstraint(
            "statement_line_id", "expense_id", name="uq_bank_allocation_pair"
        ),
        CheckConstraint(
            "allocated_amount > 0", name="bank_allocation_amount_positive"
        ),
        Index("ix_bank_allocation_statement_line_id", "statement_line_id"),
        Index("ix_bank_allocation_expense_id", "expense_id"),
    )


class BankSyncSession(UUIDPkMixin, CreatedAtMixin, Base):
    """Pending FinTS TAN session — short-lived encrypted dialog state between
    sync start and TAN entry.

    ``payload_encrypted`` is the Fernet-encrypted FinTS resume state. Deleted
    after a successful TAN or on expiry (``expires_at``) — nothing sensitive
    stays longer than needed. ``principal_id`` binds the session to the booker
    who started the sync: only they may submit the TAN."""

    __tablename__ = "bank_sync_session"

    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("account.id", ondelete="CASCADE")
    )
    principal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("principal.id", ondelete="CASCADE")
    )
    payload_encrypted: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_bank_sync_session_account_id", "account_id"),)


class CounterpartyMemory(UUIDPkMixin, CreatedAtMixin, Base):
    """Remembers the last chosen cost centre per counterparty IBAN.

    The matcher suggests this cost centre for the next transaction of the same
    payer/payee. ``budget_id`` is ``SET NULL`` when the cost centre is deleted."""

    __tablename__ = "counterparty_memory"

    counterparty_iban: Mapped[str] = mapped_column(Text)
    budget_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("budget.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("counterparty_iban", name="uq_counterparty_memory_iban"),
    )


class Invoice(UUIDPkMixin, CreatedAtMixin, Base):
    """Invoice — standalone receipt, optionally imported from ZUGFeRD/Factur-X.

    Bookings reference at most one invoice (1 invoice : N bookings). Not bound
    to cost centres/gremien (like accounts)."""

    __tablename__ = "invoice"

    number: Mapped[str | None] = mapped_column(Text, nullable=True)
    issue_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Supplier/issuer (free text, from ZUGFeRD SellerTradeParty or manual).
    supplier: Mapped[str | None] = mapped_column(Text, nullable=True)
    net_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    tax_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(CHAR(3), server_default="EUR")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 'open' | 'paid'.
    status: Mapped[str] = mapped_column(Text, server_default="open")
    # Original receipt (PDF/XML) in object storage.
    file_object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_mime: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("currency = 'EUR'", name="invoice_currency_eur"),
        CheckConstraint("status IN ('open', 'paid')", name="invoice_status_valid"),
        CheckConstraint("gross_amount >= 0", name="invoice_gross_nonneg"),
        Index("ix_invoice_number", "number"),
        Index("ix_invoice_issue_date", "issue_date"),
    )


__all__ = [
    "Account",
    "BankAllocation",
    "BankStatementLine",
    "BankSyncSession",
    "Budget",
    "BudgetAllocation",
    "BudgetExpense",
    "CounterpartyMemory",
    "FiscalYear",
]
