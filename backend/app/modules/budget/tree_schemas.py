"""API-Schemata des Budget-Baums (CR #76/#78, api.md »budget«).

camelCase-Aliase via :class:`_CamelModel` (``by_alias``); Geld als ``Decimal``
(numeric(12,2)); Datum als ``date``. ``pathKey`` ist server-gepflegt → im Request
nicht akzeptiert, nur in Out-DTOs.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.modules.budget.schemas import _CamelModel

# Obergrenze für Geldbeträge = DB-Spalte ``numeric(12, 2)``. Als ``le``-Schranke auf
# den Eingabe-Feldern, damit ein zu großer Betrag ein sauberes 422 liefert statt eines
# numeric-overflow-500 beim INSERT (#sec-audit).
_MAX_AMOUNT = Decimal("9999999999.99")


# --------------------------------------------------------------------- nodes
class BudgetNodeCreate(_CamelModel):
    """Kostenstelle anlegen. ``parentId=null`` → Top-Level (``gremiumId`` Pflicht).

    ``fiscalStartMonth``/``fiscalStartDay`` = HHJ-Stichtag (nur am Top-Level relevant;
    Default 01.01.)."""

    key: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    parent_id: UUID | None = Field(default=None, alias="parentId")
    gremium_id: UUID | None = Field(default=None, alias="gremiumId")
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    active: bool = True
    color: str | None = None
    fiscal_start_month: int = Field(default=1, ge=1, le=12, alias="fiscalStartMonth")
    # 1..28: der HHJ-Stichtag muss in **jedem** Monat existieren (sonst 31.04. / 30.02. →
    # ``date(...)`` ValueError → 500, der das Budget unbrauchbar macht, #sec-audit).
    fiscal_start_day: int = Field(default=1, ge=1, le=28, alias="fiscalStartDay")


class BudgetNodeUpdate(_CamelModel):
    """Kostenstelle teil-aktualisieren (Key/Parent unveränderlich → Pfad-Stabilität).

    ``None`` = unverändert. ``color=""`` löscht die Farbe. ``acceptedStateKeys``/
    ``deniedStateKeys``/``fiscalStart*`` nur am Top-Level sinnvoll."""

    key: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    active: bool | None = None
    color: str | None = None
    accepted_state_keys: list[str] | None = Field(default=None, alias="acceptedStateKeys")
    denied_state_keys: list[str] | None = Field(default=None, alias="deniedStateKeys")
    hidden_in_budget: bool | None = Field(default=None, alias="hiddenInBudget")
    # Sichtbarkeits-Gremium (#budget-scope) — ``None`` im Payload löscht die Zuordnung.
    view_gremium_id: UUID | None = Field(default=None, alias="viewGremiumId")
    fiscal_start_month: int | None = Field(default=None, ge=1, le=12, alias="fiscalStartMonth")
    # 1..28: siehe ``BudgetNodeCreate`` — Stichtag muss in jedem Monat existieren.
    fiscal_start_day: int | None = Field(default=None, ge=1, le=28, alias="fiscalStartDay")


class BudgetNodeOut(_CamelModel):
    """Stammdaten eines Knotens."""

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
    """Budget-Sicht eines Knotens in **einem** HHJ (R7.1b/c, #25).

    ``committed`` = ``bound + expended`` (Gesamt-Verbrauch, abwärtskompatibel).
    ``available = allocated − bound − expended + income``.
    """

    fiscal_year_id: UUID = Field(alias="fiscalYearId")
    allocated: Decimal
    # Gebunden: angenommene Anträge, anteilig um gebundene Ausgaben gemindert.
    bound: Decimal = Decimal("0")
    # Ausgegeben: tatsächliche Ausgaben (kind='expense').
    expended: Decimal = Decimal("0")
    # Einnahmen (kind='income') — erhöhen das verfügbare Budget.
    income: Decimal = Decimal("0")
    committed: Decimal
    requested: Decimal = Decimal("0")
    available: Decimal


class BudgetTreeNodeOut(_CamelModel):
    """Baumknoten + Summen je HHJ + Kinder (rekursiv) — ``GET /budgets``."""

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
    """Haushaltsjahr anlegen — nur das **Jahr** (Start/Ende aus Budget-Stichtag)."""

    year: int = Field(ge=1900, le=2200)
    active: bool = True


class FiscalYearUpdate(_CamelModel):
    """Haushaltsjahr ändern (Jahr und/oder Aktiv-Status; Disjunktheit erneut geprüft)."""

    year: int | None = Field(default=None, ge=1900, le=2200)
    active: bool | None = None


class FiscalYearOut(_CamelModel):
    """Haushaltsjahr-Stammdaten. ``display`` = ``YYYY`` (Stichtag 01.01.) bzw. ``YYYY/YY``."""

    id: UUID
    budget_id: UUID = Field(alias="budgetId")
    year: int
    display: str
    start_date: date = Field(alias="startDate")
    end_date: date = Field(alias="endDate")
    active: bool


# ----------------------------------------------------------------- allocation
class AllocationSet(_CamelModel):
    """Top-Down-Zuteilung setzen (``PUT …/allocations/{fiscalYearId}``)."""

    allocated: Decimal = Field(ge=0, allow_inf_nan=False)


class AllocationOut(_CamelModel):
    """Ergebnis einer Zuteilung."""

    budget_id: UUID = Field(alias="budgetId")
    fiscal_year_id: UUID = Field(alias="fiscalYearId")
    allocated: Decimal


# ------------------------------------------------------------------- assign
class AssignBudgetRequest(_CamelModel):
    """Antrag einer Kostenstelle zuordnen; setzt zugleich HHJ (R7.1e).

    ``budgetId=null`` löst die Zuordnung (auch ``fiscalYearId`` → null).

    ``fiscalYearId`` ist optional: wird es gesetzt, muss es zum Top-Budget der
    Kostenstelle gehören; bleibt es offen, leitet der Service das **eine** aktive HHJ
    ab und verlangt sonst eine explizite Wahl (422 — wie bei Ausgaben).
    """

    budget_id: UUID | None = Field(default=None, alias="budgetId")
    fiscal_year_id: UUID | None = Field(default=None, alias="fiscalYearId")


class MoveFiscalYearRequest(_CamelModel):
    """Antrag in anderes HHJ verschieben (``fiscalYearId`` des Top-Budgets)."""

    fiscal_year_id: UUID = Field(alias="fiscalYearId")


class AssignBudgetOut(_CamelModel):
    """Ergebnis einer Kostenstellen-/HHJ-Zuordnung."""

    application_id: UUID = Field(alias="applicationId")
    budget_id: UUID | None = Field(alias="budgetId")
    fiscal_year_id: UUID | None = Field(alias="fiscalYearId")


class BudgetApplicationOut(_CamelModel):
    """Antrag in einer Kostenstelle (+ Unterbaum) — für die Budget-Statistik-Drilldown-
    Liste (#17). Geld als ``Decimal``; ``stage`` aus dem ``budget_entry`` (oder None)."""

    application_id: UUID = Field(alias="applicationId")
    title: str | None = None
    budget_id: UUID | None = Field(default=None, alias="budgetId")
    path_key: str | None = Field(default=None, alias="pathKey")
    fiscal_year_id: UUID | None = Field(default=None, alias="fiscalYearId")
    amount: Decimal | None = None
    currency: str | None = None
    stage: str | None = None
    state_id: UUID | None = Field(default=None, alias="stateId")
    # Aktueller Flow-State (i18n-Label + Farbe) für die Status-Spalte (#17).
    state_label: dict[str, str] | None = Field(default=None, alias="stateLabel")
    state_color: str | None = Field(default=None, alias="stateColor")
    created_at: datetime = Field(alias="createdAt")


# ------------------------------------------------------------------- expense
ExpenseKind = Literal["expense", "income"]
# Zahlungsmethode (#1-2): Überweisung | Bar | Lastschrift | Karte.
PaymentMethod = Literal["ueberweisung", "bar", "lastschrift", "karte", "paypal"]


class ExpenseCreate(_CamelModel):
    """Ausgabe/Einnahme buchen (#25) — gegen Kostenstelle + HHJ, optional an Antrag.

    * ``budgetId`` Pflicht für eigenständige Buchungen; bei gebundenen (``applicationId``
      gesetzt) wird die Kostenstelle **vom Antrag geerbt** und ``budgetId``/``fiscalYearId``
      ignoriert.
    * ``applicationId`` bindet die Buchung an einen Antrag (ersetzt dessen Bindung
      anteilig). Nur für ``kind='expense'`` erlaubt.
    * ``fiscalYearId`` optional bei eigenständigen Ausgaben: fehlt es, wird das **eine**
      aktive HHJ des Top-Budgets gewählt (mehrdeutig/keins → 422).
    """

    amount: Decimal = Field(gt=0, le=_MAX_AMOUNT, allow_inf_nan=False)
    description: str = Field(min_length=1)
    kind: ExpenseKind = "expense"
    budget_id: UUID | None = Field(default=None, alias="budgetId")
    fiscal_year_id: UUID | None = Field(default=None, alias="fiscalYearId")
    application_id: UUID | None = Field(default=None, alias="applicationId")
    account_id: UUID | None = Field(default=None, alias="accountId")
    # Zusatz-Metadaten (#1-1/#1-2/#3/#4), alle optional.
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


class ExpenseUpdate(_CamelModel):
    """Gebuchte Ausgabe/Einnahme ändern. Betrag, Beschreibung, Bankkonto, Kostenstelle
    und die Zusatz-Metadaten (Daten, Empfänger/Zahler, Anmerkungen, Belegnummer,
    Zahlungsmethode, Kategorie) sind änderbar; HHJ und Antragsbindung bleiben fix
    (Buchungsstabilität). Nur gesetzte Felder werden geschrieben; explizites ``null``
    leert ein optionales Feld (``budgetId`` ausgenommen — Pflicht-FK)."""

    amount: Decimal | None = Field(default=None, gt=0, le=_MAX_AMOUNT, allow_inf_nan=False)
    description: str | None = Field(default=None, min_length=1)
    budget_id: UUID | None = Field(default=None, alias="budgetId")
    account_id: UUID | None = Field(default=None, alias="accountId")
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
    """Gebuchte Ausgabe/Einnahme (Stammdaten)."""

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
    # ``actor`` = Principal-``sub`` (Roh-Identität, Audit). ``actorName`` ist der
    # serverseitig aufgelöste Klarname — NIE die UUID im UI zeigen (#no-uuids-in-ui).
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
    # Unterbuchungen (#subbookings): ``parentExpenseId`` gesetzt → diese Buchung IST eine
    # Unterbuchung. ``childCount`` > 0 → die Buchung HAT Unterbuchungen (aufklappbar; ihr
    # ``amount`` = Σ der Kinder und ist dann schreibgeschützt).
    parent_expense_id: UUID | None = Field(default=None, alias="parentExpenseId")
    child_count: int = Field(default=0, alias="childCount")
    created_at: datetime = Field(alias="createdAt")


# -------------------------------------------------------------------- invoices
InvoiceStatus = Literal["open", "paid"]


class InvoiceCreate(_CamelModel):
    """Rechnung anlegen (#invoices). ``grossAmount`` Pflicht; Rest optional."""

    number: str | None = None
    issue_date: date | None = Field(default=None, alias="issueDate")
    due_date: date | None = Field(default=None, alias="dueDate")
    supplier: str | None = None
    net_amount: Decimal | None = Field(default=None, alias="netAmount", ge=0, le=_MAX_AMOUNT)
    tax_amount: Decimal | None = Field(default=None, alias="taxAmount", ge=0, le=_MAX_AMOUNT)
    gross_amount: Decimal = Field(alias="grossAmount", ge=0, le=_MAX_AMOUNT)
    note: str | None = None
    status: InvoiceStatus = "open"
    # Optionaler Beleg aus dem ZUGFeRD-Import (#15): Handle auf das bereits in
    # MinIO abgelegte Original-PDF (``/invoices/parse`` liefert den Token).
    file_token: str | None = Field(default=None, alias="fileToken")
    file_name: str | None = Field(default=None, alias="fileName")
    file_mime: str | None = Field(default=None, alias="fileMime")


class InvoiceParseResult(_CamelModel):
    """Ergebnis von ``POST /invoices/parse`` (#15): geparste Kopfdaten + Handle
    auf das gespeicherte Original-PDF. Die UI füllt damit den Erfassungs-Dialog
    vor; ``fileToken`` wird beim Bestätigen an ``POST /invoices`` zurückgegeben."""

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
    # Mögliche Dublette: es existiert bereits eine Rechnung mit gleicher Nummer
    # (#invoices). Die UI warnt vor dem Bestätigen, blockt den Import aber nicht.
    duplicate: bool = False


class InvoiceFileResult(_CamelModel):
    """Ergebnis von ``POST /invoices/file`` (#invoices): Handle auf das gerade
    abgelegte Original-PDF — auch für **nicht**-ZUGFeRD-Belege. Wird wie
    ``InvoiceParseResult.fileToken`` an ``POST /invoices`` zurückgereicht."""

    file_token: str = Field(alias="fileToken")
    file_name: str = Field(alias="fileName")
    file_mime: str = Field(alias="fileMime")


class InvoiceUpdate(_CamelModel):
    """Rechnung teil-aktualisieren. Nur gesetzte Felder werden geschrieben."""

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
    """Rechnung (Stammdaten + Datei-Flag)."""

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
    """Konto anlegen — Name + IBAN (Freitext). Nicht an Kostenstellen gebunden.

    Die FinTS-**Bank-Verbindung** (``fintsEndpoint`` + ``fintsBlz``) ist optional und für alle
    Bucher gleich. Die persönlichen Zugangsdaten (Login/PIN) setzt jeder Bucher selbst im
    Buchungs-Tab (#fints-percred), nicht hier."""

    name: str = Field(min_length=1, max_length=200)
    iban: str = Field(default="", max_length=64)
    active: bool = True
    fints_endpoint: str | None = Field(default=None, alias="fintsEndpoint", max_length=500)
    fints_blz: str | None = Field(default=None, alias="fintsBlz", max_length=20)


class AccountUpdate(_CamelModel):
    """Konto teil-aktualisieren. FinTS-Verbindungsfelder: ``null``/``""`` löscht, gesetzter
    Wert überschreibt (Login/PIN sind nicht mehr Teil der Konto-Stammdaten, #fints-percred)."""

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
    """Konto-Stammdaten inkl. FinTS-Bank-Verbindung (Endpunkt + BLZ). ``fintsConfigured``
    zeigt, ob die Verbindung vollständig ist (Konto ist FinTS-fähig); persönliche Logins/PINs
    erscheinen hier nie (#fints-percred)."""

    id: UUID
    name: str
    iban: str
    active: bool
    fints_endpoint: str | None = Field(default=None, alias="fintsEndpoint")
    fints_blz: str | None = Field(default=None, alias="fintsBlz")
    # True, sobald Endpunkt + BLZ vorliegen → das Konto ist per FinTS synchronisierbar (sobald
    # ein Bucher seine persönlichen Zugangsdaten hinterlegt).
    fints_configured: bool = Field(default=False, alias="fintsConfigured")
    # Letzter bekannter Bank-Kontostand + Stichtag (#fints-konten); null = nie synchronisiert.
    fints_last_balance: Decimal | None = Field(default=None, alias="fintsLastBalance")
    fints_balance_at: datetime | None = Field(default=None, alias="fintsBalanceAt")


class AccountOption(_CamelModel):
    """Minimale Konto-Auswahl (id + Name, **keine IBAN**) für Buchungs-Dropdowns —
    lesbar für Bucher (``budget.book``/``budget.view``), ohne Konten-Stammdaten-Recht (#5-2/#2).

    ``fintsConfigured`` (kein Geheimnis) = Konto ist FinTS-fähig (Endpunkt + BLZ gesetzt);
    ``fintsHasCredential`` = der **anfragende** Bucher hat bereits eigene Zugangsdaten
    hinterlegt (#fints-percred) — sonst muss er sich beim ersten Sync verbinden."""

    id: UUID
    name: str
    fints_configured: bool = Field(default=False, alias="fintsConfigured")
    fints_has_credential: bool = Field(default=False, alias="fintsHasCredential")
    fints_last_sync_at: datetime | None = Field(default=None, alias="fintsLastSyncAt")
    # Letzter Bank-Kontostand + Stichtag (#fints-konten) für den Konten-Tab.
    fints_last_balance: Decimal | None = Field(default=None, alias="fintsLastBalance")
    fints_balance_at: datetime | None = Field(default=None, alias="fintsBalanceAt")


class FintsCredentialIn(_CamelModel):
    """Persönliche FinTS-Zugangsdaten des Buchers für ein Konto (#fints-percred).

    ``fintsPin`` ist **write-only** (nur verschlüsselt gespeichert, nie zurückgegeben). Wird
    beim ersten Verbinden im Buchungs-Tab gesetzt und bei einer Änderung ersetzt."""

    fints_login: str = Field(alias="fintsLogin", min_length=1, max_length=200)
    fints_pin: str = Field(alias="fintsPin", min_length=1, max_length=200)


class FintsCredentialStatus(_CamelModel):
    """Verbindungs-Status eines Buchers für ein Konto (#fints-percred).

    ``configured`` = Konto ist FinTS-fähig (Endpunkt + BLZ am Konto). ``hasCredential`` = der
    anfragende Bucher hat eigene Zugangsdaten hinterlegt; ``login`` ist sein Anmeldename (kein
    Geheimnis, hilft beim Wiedererkennen), die PIN erscheint nie."""

    configured: bool = False
    has_credential: bool = Field(default=False, alias="hasCredential")
    fints_login: str | None = Field(default=None, alias="fintsLogin")
    fints_last_sync_at: datetime | None = Field(default=None, alias="fintsLastSyncAt")
    # Cooldown nach Bank-Sperre/Signatur-Ablehnung (#fints-review): bis dahin lehnt der Server
    # jeden Sync ab. Das FE deaktiviert solange den Abruf-Button und warnt vor Wiederholung.
    fints_locked_until: datetime | None = Field(default=None, alias="fintsLockedUntil")


# ------------------------------------------------------- bank statement (#fints)
BankLineState = Literal["unmatched", "suggested", "matched", "ignored"]
BankSyncStatus = Literal["done", "needs_tan"]


class StatementLineOut(_CamelModel):
    """Gestageter Kontoumsatz (#fints). ``amount`` ist **vorzeichenbehaftet** (> 0 Eingang,
    < 0 Ausgang); ``kind`` ist die daraus abgeleitete Buchungsart."""

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
    created_at: datetime = Field(alias="createdAt")


class BankSyncResult(_CamelModel):
    """Ergebnis eines FinTS-Sync-Schritts (#fints).

    ``status='done'`` → ``imported``/``duplicates`` gesetzt. ``status='needs_tan'`` →
    ``sessionToken`` + ``challenge`` zeigen, dass eine TAN nötig ist (bei ``decoupled``
    genügt das Freigeben in der Banking-App + Pollen via ``POST …/tan`` ohne Code)."""

    status: BankSyncStatus
    account_id: UUID = Field(alias="accountId")
    imported: int = 0
    duplicates: int = 0
    # needs_tan:
    session_token: UUID | None = Field(default=None, alias="sessionToken")
    challenge: str | None = None
    challenge_html: str | None = Field(default=None, alias="challengeHtml")
    # Optischer Challenge (photoTAN/QR-TAN) als Data-URL zum direkten Anzeigen (#fints-qrtan).
    challenge_image: str | None = Field(default=None, alias="challengeImage")
    decoupled: bool = False


class BankTanRequest(_CamelModel):
    """TAN zum Fortsetzen einer schwebenden Sync-Sitzung (#fints). Bei *decoupled*
    pushTAN leer lassen (reiner Poll: „in der App freigegeben?")."""

    tan: str = Field(default="", max_length=100)


class BankImportResult(_CamelModel):
    """Ergebnis des Datei-Imports (CAMT.053/MT940, Option D, #fints)."""

    account_id: UUID = Field(alias="accountId")
    imported: int = 0
    duplicates: int = 0


class ConfirmLineRequest(_CamelModel):
    """Einen Umsatz zur Buchung bestätigen (#fints).

    Entweder ``matchExpenseId`` (an eine **bestehende** Buchung anhängen) **oder**
    ``budgetId`` (neue Buchung gegen diese Kostenstelle anlegen — Art aus dem Vorzeichen).
    ``fiscalYearId`` optional (sonst das eine aktive HHJ); ``description`` überschreibt den
    Default (Verwendungszweck)."""

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


# ------------------------------------------------------------------- transfer
class TransferCreate(_CamelModel):
    """Übertrag Kostenstelle → Kostenstelle (gleiches HHJ).

    Erzeugt eine Ausgabe auf ``fromBudgetId`` und eine Einnahme auf ``toBudgetId``
    (gleicher Betrag/HHJ), verknüpft über eine ``transferId``."""

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
    """Ergebnis eines Übertrags (beide Buchungs-Ids)."""

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
