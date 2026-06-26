"""Hierarchische Budgets / Kostenstellen + Haushaltsjahre (CR #76/#78, R7.1*).

Ergänzt das flache ``budget_pot``-Modell (T-17) um den **Kostenstellen-Baum**:

* :class:`Budget`            — Knoten im Baum (``parent_id`` = Self-FK; ``path_key``
  = zusammengesetzter Pfad ``VS-800-04``, vom Service gepflegt).
* :class:`FiscalYear`        — Haushaltsjahr **je Top-Level-Budget** (``budget_id``
  zeigt auf ein Top-Level; Service-Check). Disjunkt pro Top-Budget (R7.1f/g).
* :class:`BudgetAllocation`  — Top-Down-Zuteilung ``Budget × FiscalYear`` (R7.1b).
  **Verfügbare Summe = allocated; KEIN Roll-up.** Verbrauch (gebundene Summe) ist
  Roll-up aus genehmigten Anträgen (nicht persistiert; ``tree_rules.rollup_committed``).

Single-currency **EUR** (CHECK), data-model §1/§5.8. Tabellen entstehen — wie alle
Modul-Tabellen — über ``Base.metadata.create_all`` (0002); ``0020`` legt sie für
bereits migrierte Schemata idempotent nach.
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
    """Kostenstellen-Knoten (data-model §1 »budget«). ``parent_id`` NULL = Top-Level.

    ``gremium_id`` nur am Top-Level gesetzt (Kinder erben fachlich); ``key`` ist das
    Pfad-Segment, ``path_key`` der zusammengesetzte Schlüssel (``VS-800-04``). Self-FK
    ``ON DELETE RESTRICT`` — Kinder müssen zuerst gelöscht werden.
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
    # Anzeigefarbe der Kostenstelle (Pie-Charts + Baum, #budget-redesign); NULL = auto.
    color: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Nur am Top-Level relevant: Flow-State-Keys, die als angenommen (→ gebunden) bzw.
    # abgelehnt (→ ausgeschlossen) gelten. Alles andere zählt als »beantragt«.
    accepted_state_keys: Mapped[list] = mapped_column(JSONB, server_default="[]")
    denied_state_keys: Mapped[list] = mapped_column(JSONB, server_default="[]")
    # Im Budget-Tab ausblenden (#budget-hide): reine Anzeige-Einstellung — Werte
    # zählen unverändert in Eltern-Rollups/Export; nur das Dashboard filtert.
    # Python-Default zusätzlich zum Server-Default: auch frisch konstruierte
    # Instanzen (Tests/Service vor dem Flush) tragen sofort einen bool.
    hidden_in_budget: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    # Sichtbarkeits-Gremium (#budget-scope): Mitglieder dieses Gremiums sehen die
    # Kostenstelle (+ Unterbaum) im Budget-Tab als Root — ohne globale
    # budget.*-Permission. Unabhängig vom Top-Level-``gremium_id`` (Klassifikation).
    view_gremium_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("gremium.id", ondelete="SET NULL"), nullable=True
    )
    # Haushaltsjahr-Stichtag (Tag/Monat des Periodenstarts) — **nur am Top-Level**
    # relevant. Default 01.01.; abweichend (z. B. 01.07.) ⇒ HHJ-Anzeige »YYYY/YY«.
    # Die HHJ tragen nur das Jahr; Start/Ende leiten sich aus diesem Stichtag ab.
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
    """Haushaltsjahr (R7.1d) je **Top-Level**-Budget — identifiziert durch das **Jahr**.

    Keinen Freitext-Namen: das HHJ ist über ``year`` (Startjahr) eindeutig. Start/Ende
    leiten sich aus dem ``fiscal_start_month``/``fiscal_start_day`` des Top-Budgets ab
    (``start = Stichtag(year)``, ``end = Stichtag(year+1) − 1 Tag``) und werden zur
    Disjunktheits-/Filter-Nutzung mitpersistiert. Anzeige: ``YYYY`` bei Stichtag 01.01.,
    sonst ``YYYY/YY``.
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
    """Top-Down-Zuteilung ``Budget × FiscalYear`` (R7.1b).

    ``allocated`` = verfügbare Summe der Kostenstelle in diesem HHJ. Service-Invariante:
    Σ ``allocated`` der direkten Kinder ≤ ``allocated`` des Parents (je HHJ).
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
    """Tatsächliche **Ausgabe oder Einnahme** gegen eine Kostenstelle + HHJ (#25).

    Direkte Buchung (z. B. Barauslage, Rechnung, Sponsoring) auf einen Budget-Knoten.

    * ``kind='expense'`` zählt als **ausgegeben** (expended) und mindert das Budget.
    * ``kind='income'`` zählt als **Einnahme** und erhöht das verfügbare Budget.
    * ``application_id`` (optional, **nicht** unique → mehrere Teil-Ausgaben je Antrag):
      eine an einen Antrag gebundene Ausgabe **ersetzt** dessen gebundenen (committed)
      Betrag anteilig (``bound(app) = max(0, amount − Σ gebundene Ausgaben)``).
      Kostenstelle + HHJ werden vom Antrag geerbt (Service-Invariante). Einnahmen sind
      stets eigenständig (``application_id`` null).

    ``fiscal_year_id`` muss zum Top-Level des Knotens gehören (Service-Check).
    """

    __tablename__ = "budget_expense"

    budget_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("budget.id", ondelete="CASCADE")
    )
    fiscal_year_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fiscal_year.id", ondelete="CASCADE")
    )
    # Gebuchte Buchung gegen **einen** Antrag (ersetzt dessen Bindung anteilig) oder
    # eigenständig (``None``). ``SET NULL`` beim Löschen des Antrags → die Buchung bleibt
    # als eigenständige Ausgabe erhalten.
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("application.id", ondelete="SET NULL"), nullable=True
    )
    # Optionales Konto (Bankkonto, frei verwaltet; NICHT an Kostenstellen gebunden).
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("account.id", ondelete="SET NULL"), nullable=True
    )
    # Optionale Rechnung (#invoices): 1 Rechnung : N Buchungen. SET NULL beim Löschen
    # der Rechnung → die Buchung bleibt bestehen.
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("invoice.id", ondelete="SET NULL"), nullable=True
    )
    # Verknüpft die beiden Buchungen eines Übertrags (Ausgabe Quelle ↔ Einnahme Ziel).
    transfer_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    # 'expense' (ausgegeben) | 'income' (Einnahme).
    kind: Mapped[str] = mapped_column(Text, server_default="expense")
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(CHAR(3), server_default="EUR")
    description: Mapped[str] = mapped_column(Text)
    actor: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Zusatz-Metadaten (#1-1/#1-2/#3/#4), alle optional:
    # Rechnungs- und Zahldatum (fachliche Daten, unabhängig von created_at).
    invoice_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    payment_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Empfänger/Zahler (Freitext): von wem (Einnahme) / für wen (Ausgabe).
    correspondent: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Anmerkungen (mehrzeiliger Freitext).
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Belegnummer (Rechnungs-/Belegreferenz, Freitext).
    reference_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Zahlungsmethode: ueberweisung | bar | lastschrift | karte.
    payment_method: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Kategorie/Tag (Freitext) zur Gruppierung jenseits der Kostenstelle.
    category: Mapped[str | None] = mapped_column(Text, nullable=True)

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
    )


class Account(UUIDPkMixin, CreatedAtMixin, Base):
    """Konto (z. B. Bankkonto) — frei verwaltet, **nicht** an Kostenstellen gebunden.

    Dient als optionale Referenz bei Buchungen (welches Konto bewegt wurde). ``iban``
    ist Freitext (keine Format-/Prüfsummen-Validierung)."""

    __tablename__ = "account"

    name: Mapped[str] = mapped_column(Text)
    iban: Mapped[str] = mapped_column(Text, server_default="")
    active: Mapped[bool] = mapped_column(Boolean, server_default="true")

    # — FinTS-Bankabgleich (#fints): nur die **Bank-Verbindung** (Endpunkt + BLZ) liegt am
    #   Konto — sie ist für alle Bucher gleich und wird vom Admin gesetzt. Die **persönlichen**
    #   Zugangsdaten (Login + PIN + TAN-Methode + Client-Zustand) sind je Principal getrennt
    #   in :class:`AccountFintsCredential` — verschiedene Bucher haben für dasselbe Konto eigene
    #   Online-Banking-Logins, und der SCA-Client-Zustand (``system_id``) ist an Nutzer+Gerät
    #   gebunden (geteilter Zustand bräche TAN/SCA, #fints-percred). Ohne ``fints_endpoint`` +
    #   ``fints_blz`` ist das Konto nicht FinTS-fähig.
    fints_endpoint: Mapped[str | None] = mapped_column(Text, nullable=True)
    fints_blz: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_account_name", "name"),)


class AccountFintsCredential(UUIDPkMixin, CreatedAtMixin, Base):
    """Persönliche FinTS-Zugangsdaten **eines Principals für ein Konto** (#fints-percred).

    Mehrere Bucher teilen sich dasselbe Bankkonto, haben aber je **eigene** Online-Banking-
    Logins. Login + PIN gehören daher dem einzelnen Nutzer, nicht dem Konto. Die PIN liegt
    **nur verschlüsselt** vor (Fernet, ``app.shared.crypto``) und wird nie im Klartext
    zurückgegeben. ``fints_state`` ist der verschlüsselte, serialisierte FinTS-Client-Zustand
    (``system_id`` u. a.) für das ~90-Tage-SCA-Fenster — er ist an **Nutzer + Gerät** gebunden,
    deshalb pro Credential getrennt; ``fints_tan_mechanism`` die zuletzt gewählte TAN-Methode.
    Beide FKs ``ON DELETE CASCADE``: gelöschtes Konto/gelöschter Principal räumt das Geheimnis
    mit ab.
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
    # Sperr-Cooldown (#fints-review): nach einer Bank-Sperre/Signatur-Ablehnung gesetzt; bis
    # zu diesem Zeitpunkt verweigert der Service jeden Sync, damit wiederholte Versuche nicht
    # auf das Bank-Fehlversuchskonto einzahlen und die Sperre verschärfen.
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
    """Einzelner Kontoumsatz (#fints) — **gestaged**, bevor er zur Buchung wird.

    Aus FinTS-Abruf oder Datei-Import (CAMT.053/MT940). ``idempotency_key`` macht den
    Re-Import idempotent (``ON CONFLICT DO NOTHING``). ``amount`` ist **vorzeichenbehaftet**
    (>0 Eingang, <0 Ausgang); beim Bestätigen wird daraus ``budget_expense`` mit
    ``kind`` aus dem Vorzeichen und ``amount = abs(...)`` (DB-CHECK ``amount > 0``).
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
    # Matcher-Vorschlag (nur Hinweis für die UI; verbindlich erst beim Bestätigen).
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
    """Zuordnung Kontoumsatz ↔ Buchung (N:M — Teil-/Sammelzahlungen).

    Ein Umsatz kann auf mehrere Buchungen aufgeteilt werden und eine Buchung von
    mehreren Umsätzen bezahlt werden. ``allocated_amount`` ist der zugeordnete Teilbetrag
    (positiv). CASCADE beidseits: gelöschte Buchung/gelöschter Umsatz löst die Zuordnung.
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
    """Schwebende FinTS-TAN-Sitzung (#fints) — **kurzlebiger**, verschlüsselter Dialog-
    Zustand zwischen Start-Sync und TAN-Eingabe.

    ``payload_encrypted`` ist der Fernet-verschlüsselte FinTS-Resume-Zustand
    (Client-/Dialog-/TAN-Blob). Nach erfolgreicher TAN oder Ablauf (``expires_at``)
    gelöscht — nichts Sensibles bleibt länger als nötig liegen (security.md). ``principal_id``
    bindet die Sitzung an den Bucher, der den Sync startete: nur er darf die TAN einreichen
    (#fints-percred)."""

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
    """Merkt je Gegen-IBAN die zuletzt gewählte Kostenstelle (#fints-matching).

    Beim nächsten Umsatz desselben Zahlers/Empfängers schlägt der Matcher diese
    Kostenstelle vor. ``budget_id`` ``SET NULL`` beim Löschen der Kostenstelle."""

    __tablename__ = "counterparty_memory"

    counterparty_iban: Mapped[str] = mapped_column(Text)
    budget_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("budget.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("counterparty_iban", name="uq_counterparty_memory_iban"),
    )


class Invoice(UUIDPkMixin, CreatedAtMixin, Base):
    """Rechnung (#invoices) — eigenständiger Beleg, optional aus ZUGFeRD/Factur-X
    importiert. Buchungen referenzieren optional **eine** Rechnung (1 Rechnung : N
    Buchungen). Nicht an Kostenstellen/Gremien gebunden (wie Konten)."""

    __tablename__ = "invoice"

    number: Mapped[str | None] = mapped_column(Text, nullable=True)
    issue_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Lieferant/Aussteller (Freitext, aus ZUGFeRD SellerTradeParty oder manuell).
    supplier: Mapped[str | None] = mapped_column(Text, nullable=True)
    net_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    tax_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(CHAR(3), server_default="EUR")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 'open' (offen) | 'paid' (bezahlt).
    status: Mapped[str] = mapped_column(Text, server_default="open")
    # Original-Beleg (PDF/XML) im Object-Storage.
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
