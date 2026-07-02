"""Gemeinsamer Unterbau der :class:`~.service.BankService`-Teilklassen (#fints).

Konstruktor + Helfer, die mehrere Teilbereiche (Credentials, Sync, Staging, Reconcile,
Listing) brauchen: Feature-/Principal-Gates, Konto-/Credential-Lookup, Audit-Hook,
Kontostand-Übernahme und die Ausgabe-Projektion eines gestageten Umsatzes.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.budget.bank import normalize, statement
from app.modules.budget.tree_models import (
    Account,
    AccountFintsCredential,
    BankStatementLine,
    Budget,
)
from app.modules.budget.tree_schemas import StatementLineOut
from app.settings import Settings, get_settings
from app.shared.errors import NotFoundError, ServiceUnavailableError, ValidationProblem

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# Obergrenze für die Zeilenzahl eines Imports/Abrufs (Anti-DoS): ein 10-MiB-MT940 kann
# zehntausende Umsätze tragen; jede Zeile macht im Staging 1-2 Queries (#fints-review).
MAX_STATEMENT_LINES = 10_000


class BankServiceBase:
    """FinTS-/Datei-gestützter Kontoabgleich (an eine Session gebunden) — Unterbau."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        settings: Settings | None = None,
        actor: str | None = None,
        principal_id: uuid.UUID | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.actor = actor
        # Persönliche FinTS-Zugangsdaten + TAN-Sitzungen sind je Bucher getrennt
        # (#fints-percred); der Sync/Credential-Pfad braucht daher die Principal-Id. Der
        # Datei-Import (kein Bankzugang) kommt ohne aus.
        self.principal_id = principal_id

    # ----------------------------------------------------------------- helpers
    def _require_enabled(self) -> str:
        """FinTS-Verschlüsselungs-Schlüssel oder 503 (Feature aus)."""
        key = self.settings.fints_enc_key
        if not key:
            raise ServiceUnavailableError("FinTS is not configured (no encryption key set).")
        return key

    def _require_principal(self) -> uuid.UUID:
        """Principal-Id des Buchers oder 503 (interne Invariante: der Router liefert sie
        immer für authentifizierte FinTS-Aufrufe, #fints-percred)."""
        if self.principal_id is None:
            raise ServiceUnavailableError("FinTS requires an authenticated principal.")
        return self.principal_id

    async def _load_credential(self, account_id: uuid.UUID) -> AccountFintsCredential:
        """Persönliche Zugangsdaten des Buchers für ein Konto laden — oder 422
        ``fints_no_credential`` (das FE fordert dann das erstmalige Verbinden, #fints-percred)."""
        cred = await self.session.scalar(
            select(AccountFintsCredential).where(
                AccountFintsCredential.account_id == account_id,
                AccountFintsCredential.principal_id == self._require_principal(),
            )
        )
        if cred is None:
            raise ValidationProblem(
                "No personal FinTS login stored for this account — connect first.",
                code="fints_no_credential",
            )
        return cred

    async def _account_or_404(self, account_id: uuid.UUID) -> Account:
        acc = await self.session.get(Account, account_id)
        if acc is None:
            raise NotFoundError(f"account {account_id} not found")
        return acc

    async def _audit(
        self, action: AuditAction, *, target_id: str, data: dict | None = None
    ) -> None:
        await audit_record(
            self.session,
            actor=self.actor,
            action=action,
            target_type="bank",
            target_id=target_id,
            data=data or {},
        )

    @staticmethod
    def _apply_balance(acc: Account, balance: statement.StatementBalance | None) -> None:
        """Bank-Kontostand + Stichtag am Konto ablegen (#fints-konten). Nur überschreiben, wenn
        ein Saldo geliefert wurde (HKSAL/`:62F:`/CLBD); sonst bleibt der letzte bekannte Stand."""
        if balance is None:
            return
        as_of = (
            datetime.combine(balance.as_of, datetime.min.time(), tzinfo=UTC)
            if balance.as_of is not None
            else datetime.now(UTC)
        )
        # Recency-Guard (#review): einen neueren Stand NICHT durch einen älteren Datei-Import
        # überschreiben. Bei gleichem/keinem Stichtag (None) immer aktualisieren.
        if (
            acc.fints_balance_at is not None
            and balance.as_of is not None
            and as_of < acc.fints_balance_at
        ):
            return
        acc.fints_last_balance = balance.amount
        acc.fints_balance_at = as_of

    @staticmethod
    def _line_out(line: BankStatementLine, suggested_path_key: str | None) -> StatementLineOut:
        # Gegenkonto + Zweck IMMER aus den Rohdaten auflösen (#fints-raw) — nie aus den
        # gespeicherten counterparty_*/purpose-Spalten (die könnten von einer älteren Parser-
        # Version stammen, z. B. „KRZL"/geklebte IBAN/verklebter Zweck). MT940/FinTS liefert über
        # die Rohfelder ein sauberes Ergebnis; CAMT-Roh ohne GVC-Felder → Fallback auf die Spalte.
        name, iban = normalize.resolve_counterparty(line.raw_payload, credit=line.amount > 0)
        if not name and not iban:
            # Fallback auf die gespeicherte Spalte (CAMT/alt) — Platzhalter trotzdem verwerfen.
            name = normalize.clean_counterparty_name(line.counterparty_name)
            iban = line.counterparty_iban
        purpose = normalize.resolve_purpose(line.raw_payload)
        if purpose is None:
            purpose = line.purpose
        # Sparkassen-Sammelbuchungszwecke („DATEI-NR. …") menschenlesbar machen (#fints-batch)
        # — reine Anzeige; Spalte/Rohdaten bleiben unverändert.
        purpose = normalize.prettify_purpose(purpose)
        return StatementLineOut(
            id=line.id,
            accountId=line.account_id,
            amount=line.amount,
            kind="income" if line.amount > 0 else "expense",
            currency=line.currency,
            bookingDate=line.booking_date,
            valueDate=line.value_date,
            purpose=purpose,
            counterpartyName=name,
            counterpartyIban=iban,
            endToEndId=line.end_to_end_id,
            reference=line.reference,
            matchState=line.match_state,  # type: ignore[arg-type]
            suggestedBudgetId=line.suggested_budget_id,
            suggestedPathKey=suggested_path_key,
            suggestedExpenseId=line.suggested_expense_id,
            createdAt=line.created_at,
        )

    async def _path_keys(self, budget_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
        if not budget_ids:
            return {}
        rows = (
            await self.session.execute(
                select(Budget.id, Budget.path_key).where(Budget.id.in_(budget_ids))
            )
        ).all()
        return {bid: pk for bid, pk in rows}
