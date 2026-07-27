"""Hierarchical budgets and cost centers plus fiscal years.

``Budget`` is a tree node with a ``parent_id`` self-FK. The service maintains
``path_key``, the composed key in the form ``VS-800-04``. ``FiscalYear``
belongs to a top-level budget (service check). ``BudgetAllocation`` is the
top-down allocation ``Budget x FiscalYear``. Available equals allocated, with
NO roll-up. Consumption rolls up from the approved applications. It is not
persisted, see ``tree_rules.rollup_committed``. The only currency is EUR
(CHECK).
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
    """Cost-center node. A NULL ``parent_id`` marks the top level.

    Only the top level carries ``gremium_id``. The children inherit it
    logically. ``key`` is the path segment. ``path_key`` is the composed key,
    for example ``VS-800-04``. The self-FK uses ``ON DELETE RESTRICT``, so you
    must delete the children first.
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
    # Display color for the pie charts and the tree. NULL selects an auto color.
    color: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Top level only: flow-state keys that count as accepted (-> committed) or
    # as denied (-> excluded). Every other state counts as requested.
    accepted_state_keys: Mapped[list] = mapped_column(JSONB, server_default="[]")
    denied_state_keys: Mapped[list] = mapped_column(JSONB, server_default="[]")
    # Hides the node in the budget tab. Display only: the values still count in
    # the parent rollups and in the export. A Python default backs up the
    # server default, so a new instance carries a bool before the flush.
    hidden_in_budget: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    # Visibility Gremium: its members see this cost center and its subtree as a
    # root in the budget tab without a global budget.* permission. This is
    # independent of the top-level ``gremium_id`` classification.
    view_gremium_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("gremium.id", ondelete="SET NULL"), nullable=True
    )
    # Fiscal-year cutoff, the day and the month of the period start. Top level
    # only. The default is Jan 1. A different cutoff renders a fiscal year as
    # "YYYY/YY". A fiscal year stores only the year. Start and end derive from
    # this cutoff.
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
    """Fiscal year of one top-level budget, identified by ``year``, the start year.

    A fiscal year has no free-text name. Start and end derive from
    ``fiscal_start_month`` and ``fiscal_start_day`` of the top budget
    (``start = cutoff(year)``, ``end = cutoff(year+1) - 1 day``). Both stay
    persisted for the disjointness check and for filtering. The UI shows
    ``YYYY`` for a Jan-1 cutoff and ``YYYY/YY`` for any other cutoff.
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

    ``allocated`` is the available sum of the cost center in this fiscal year.
    Service invariant: the sum of ``allocated`` over the direct children must
    not exceed the value of the parent, per fiscal year.
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
    """Actual expense or income booked against a cost center and a fiscal year.

    ``kind='expense'`` reduces the budget. ``kind='income'`` increases it.
    ``application_id`` is optional and NOT unique, because one application can
    carry several partial expenses. An application-bound expense replaces the
    committed amount of that application pro rata
    (``bound(app) = max(0, amount - sum of bound expenses)``). Such an expense
    inherits cost center and fiscal year from the application (service
    invariant). An income row is always standalone with a null
    ``application_id``. ``fiscal_year_id`` must belong to the top level of the
    node (service check).
    """

    __tablename__ = "budget_expense"

    budget_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("budget.id", ondelete="CASCADE")
    )
    fiscal_year_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fiscal_year.id", ondelete="CASCADE")
    )
    # Booked against one application: the expense then replaces the binding of
    # that application pro rata. A standalone booking uses ``None``.
    # ``SET NULL`` on application delete keeps the booking as a standalone
    # expense.
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("application.id", ondelete="SET NULL"), nullable=True
    )
    # Optional bank account. An account is independent of the cost-center tree.
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("account.id", ondelete="SET NULL"), nullable=True
    )
    # Optional invoice. One invoice can carry N bookings. SET NULL on invoice
    # delete keeps the booking.
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
    # Business dates for invoice and payment, independent of ``created_at``.
    invoice_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    payment_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Free-text correspondent: from whom for an income, for whom for an expense.
    correspondent: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Free-text reference of the receipt or of the invoice.
    reference_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Payment method: ueberweisung | bar | lastschrift | karte | paypal.
    payment_method: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Free-text category or tag. It groups bookings beyond the cost center.
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Sub-booking: points at the parent booking. A child INHERITS account, cost
    # center, fiscal year and kind from the parent. The child stores copies of
    # these column values, so the rollups and the queries still apply. A child
    # carries only its own amount, description, dates, receipt and bank link.
    # The parent amount is the sum of its children. The budget rollup counts
    # parents only (parent_expense_id IS NULL). Children are a pure breakdown.
    # CASCADE: a delete of the parent deletes its children.
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
    """Account, for example a bank account. It is not bound to a cost center.

    An admin manages the accounts freely. A booking can reference an account to
    record which account moved the money. ``iban`` is free text. The platform
    validates neither its format nor its checksum.
    """

    __tablename__ = "account"

    name: Mapped[str] = mapped_column(Text)
    iban: Mapped[str] = mapped_column(Text, server_default="")
    active: Mapped[bool] = mapped_column(Boolean, server_default="true")

    # FinTS: only the bank connection lives on the account, the endpoint and the
    # BLZ. The admin sets it and all bookers share it. Personal credentials live
    # per principal in ``AccountFintsCredential``. The SCA client state is bound
    # to user and device, because a shared state would break the TAN and SCA
    # flow. Without ``fints_endpoint`` and ``fints_blz`` the account cannot use
    # FinTS.
    fints_endpoint: Mapped[str | None] = mapped_column(Text, nullable=True)
    fints_blz: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Last known account balance. It comes from the closing balance of a sync
    # (HKSAL) or from the ``:62F:``/CLBD balance of a file import.
    # ``fints_balance_at`` is the as-of time of that balance. The value serves
    # display and reconciliation only. It is not part of the budget math.
    fints_last_balance: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    fints_balance_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (Index("ix_account_name", "name"),)


class AccountFintsCredential(UUIDPkMixin, CreatedAtMixin, Base):
    """Personal FinTS credentials of one principal for one account.

    Bookers share the bank account, but each booker has a separate
    online-banking login. Therefore login and PIN belong to the user, not to the
    account. The platform stores the PIN encrypted only (Fernet,
    ``app.shared.crypto``) and never returns it in plaintext. ``fints_state``
    holds the encrypted serialized FinTS client state (``system_id`` and more)
    for the SCA window of about 90 days. That state is bound to user and
    device, so each credential keeps its own copy. Both FKs use
    ``ON DELETE CASCADE``: a delete of the account or of the principal removes
    the secret.
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
    # Lock cooldown. The service sets it after a bank lock or after a rejected
    # signature. Until that time the service refuses a sync, so that retries do
    # not make the bank-side lock worse.
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
    """Single bank transaction, staged before it becomes a booking.

    The line comes from a FinTS fetch or from a file import (CAMT.053/MT940).
    ``idempotency_key`` makes a re-import idempotent
    (``ON CONFLICT DO NOTHING``). ``amount`` is signed: above 0 for an inflow,
    below 0 for an outflow. On confirm the line becomes a ``budget_expense``
    with ``kind`` from the sign and ``amount = abs(...)``, because the DB CHECK
    demands ``amount > 0``.
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
    # Matcher suggestion. It is a UI hint. Only a confirm makes it binding.
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
    """Bank line to booking link, N:M for partial and collective payments.

    One transaction can split across several bookings. Several transactions can
    pay one booking. ``allocated_amount`` is the allocated partial amount and
    is positive. Both FKs use CASCADE.
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
    """Pending FinTS TAN session with short-lived encrypted dialog state.

    The state lives between the sync start and the TAN entry.
    ``payload_encrypted`` is the Fernet-encrypted FinTS resume state. The
    service deletes the session after a successful TAN or at ``expires_at``, so
    that no sensitive data stays longer than needed. ``principal_id`` binds the
    session to the booker who started the sync. Only that booker may submit the
    TAN.
    """

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
    """Remembers the last chosen cost center per counterparty IBAN.

    The matcher suggests this cost center for the next transaction of the same
    payer or payee. A delete of the cost center sets ``budget_id`` to NULL
    (``SET NULL``).
    """

    __tablename__ = "counterparty_memory"

    counterparty_iban: Mapped[str] = mapped_column(Text)
    budget_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("budget.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("counterparty_iban", name="uq_counterparty_memory_iban"),
    )


class Invoice(UUIDPkMixin, CreatedAtMixin, Base):
    """Invoice: a standalone receipt, optionally imported from ZUGFeRD/Factur-X.

    A booking references at most one invoice. One invoice can carry N bookings.
    An invoice is not bound to a cost center or to a Gremium, like an account.
    """

    __tablename__ = "invoice"

    number: Mapped[str | None] = mapped_column(Text, nullable=True)
    issue_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Free-text supplier or issuer, from the ZUGFeRD SellerTradeParty or manual.
    supplier: Mapped[str | None] = mapped_column(Text, nullable=True)
    net_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    tax_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(CHAR(3), server_default="EUR")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 'open' | 'paid'.
    status: Mapped[str] = mapped_column(Text, server_default="open")
    # Original receipt as PDF or XML in the object storage.
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
