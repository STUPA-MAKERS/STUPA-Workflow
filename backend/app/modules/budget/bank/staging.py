"""Datei-Import + idempotentes Staging von Kontoumsätzen (#fints).

Beide Quellen (FinTS-Abruf, Datei-Import) münden hier: Zeilen werden mit
Idempotenz-Schlüsseln versehen, format-übergreifend dedupliziert (#fints-batch),
per ``ON CONFLICT DO NOTHING`` eingespielt und mit einem Buchungs-Vorschlag versehen.

**Format-Wechsel MT940 ↔ CAMT:** die Idempotenz-Schlüssel beider Formate sind nicht
kompatibel (andere Bank-Referenz, andere Rohfelder). Damit der Umstieg auf den
CAMT-Abruf das Abruf-Fenster nicht als Dubletten re-importiert, gleicht
:meth:`StagingOps._consume_fingerprint` eingehende Zeilen zusätzlich inhaltlich
(Wertstellung + Betrag + E2E-Ref bzw. kanonischer Zweck + Gegen-IBAN) gegen den
Bestand ab. Aufgeteilte Sammelbuchungen ersetzen zudem ihre alte, ungebuchte
Gesamt-Zeile (:meth:`StagingOps._supersede_batch_totals`).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.modules.audit.actions import AuditAction
from app.modules.budget.bank import dedup, match, statement
from app.modules.budget.bank.service_base import MAX_STATEMENT_LINES, BankServiceBase
from app.modules.budget.tree_models import (
    Account,
    BankAllocation,
    BankStatementLine,
    BudgetExpense,
    CounterpartyMemory,
)
from app.modules.budget.tree_schemas import BankImportResult
from app.shared.errors import ValidationProblem


@dataclass(slots=True)
class _Fingerprint:
    """Inhaltlicher Vergleichs-Schlüssel einer Zeile (format-unabhängig, #fints-batch)."""

    value_date: date | None
    amount: Decimal
    end_to_end: str | None
    purpose_key: str
    counterparty_iban: str | None


class StagingOps(BankServiceBase):
    """Staging-Pfad: Datei-Import, Einspielen, Vorschlag."""

    async def import_file(
        self, account_id: uuid.UUID, data: bytes, *, filename: str | None
    ) -> BankImportResult:
        """Option D (#fints): CAMT.053/MT940-Datei parsen + Umsätze stagen."""
        acc = await self._account_or_404(account_id)
        max_bytes = self.settings.attachment_max_bytes
        if len(data) > max_bytes:
            raise ValidationProblem(f"File exceeds {max_bytes} bytes.", code="file_too_large")
        try:
            lines, balance = statement.parse_statement_full(data, filename=filename)
        except statement.StatementParseError as exc:
            raise ValidationProblem(
                "File is neither valid CAMT.053 nor MT940.", code="bank_statement_unparseable"
            ) from exc
        self._apply_balance(acc, balance)
        imported, duplicates, superseded = await self._stage_lines(acc, lines)
        await self._audit(
            AuditAction.BANK_STATEMENT_IMPORT,
            target_id=str(acc.id),
            data={
                "imported": imported,
                "duplicates": duplicates,
                "superseded": superseded,
                "source": "file",
            },
        )
        await self.session.commit()
        return BankImportResult(accountId=acc.id, imported=imported, duplicates=duplicates)

    # ---------------------------------------------------------------- staging
    async def _stage_lines(
        self, acc: Account, lines: list[statement.StatementLine]
    ) -> tuple[int, int, int]:
        """Umsätze idempotent einspielen (``ON CONFLICT DO NOTHING``) + Vorschläge setzen.

        Liefert ``(neu, dubletten, ersetzte_sammel_zeilen)``."""
        if len(lines) > MAX_STATEMENT_LINES:
            raise ValidationProblem(
                f"Statement has too many transactions (>{MAX_STATEMENT_LINES}).",
                code="bank_statement_too_large",
            )
        # EUR-only Ledger (DB-CHECK): Fremdwährungen NICHT still als EUR umdeuten, sondern
        # klar ablehnen (#fints-review) — Cent-Beträge wären sonst falsch attribuiert.
        non_eur = next((line.currency for line in lines if line.currency != "EUR"), None)
        if non_eur is not None:
            raise ValidationProblem(
                f"Only EUR transactions are supported (got {non_eur}).",
                code="bank_statement_currency_unsupported",
            )
        scope = acc.iban or str(acc.id)
        dedup.assign_keys(scope, lines)
        known = await self._existing_fingerprints(acc.id, lines)
        imported = 0
        for line in lines:
            # Format-übergreifende Inhalts-Dublette (MT940 ↔ CAMT, #fints-batch): derselbe
            # Umsatz aus dem jeweils anderen Format hat einen anderen Idempotenz-Schlüssel
            # und käme am ON CONFLICT vorbei.
            if self._consume_fingerprint(known, _line_fingerprint(line)):
                continue
            suggested_budget, suggested_expense = await self._suggest(line)
            state = "suggested" if (suggested_budget or suggested_expense) else "unmatched"
            stmt = (
                pg_insert(BankStatementLine)
                .values(
                    id=uuid.uuid4(),
                    account_id=acc.id,
                    idempotency_key=line.idempotency_key,
                    raw_payload=line.raw,
                    booking_date=line.booking_date,
                    value_date=line.value_date,
                    amount=line.amount,
                    currency="EUR",
                    purpose=line.purpose,
                    counterparty_name=line.counterparty_name,
                    counterparty_iban=line.counterparty_iban,
                    end_to_end_id=line.end_to_end_id,
                    reference=line.reference,
                    match_state=state,
                    suggested_budget_id=suggested_budget,
                    suggested_expense_id=suggested_expense,
                )
                .on_conflict_do_nothing(constraint="uq_bank_statement_line_idem")
                .returning(BankStatementLine.id)
            )
            if (await self.session.execute(stmt)).first() is not None:
                imported += 1
        superseded = await self._supersede_batch_totals(acc.id, lines)
        return imported, len(lines) - imported, superseded

    # --------------------------------------------- cross-format dedup (#fints-batch)
    async def _existing_fingerprints(
        self, account_id: uuid.UUID, lines: list[statement.StatementLine]
    ) -> dict[tuple[str, str], int]:
        """Inhalts-Fingerprints der bereits gestageten Zeilen im Wertstellungs-Fenster der
        eingehenden Zeilen — als Multiset (mehrere identische Zahlungen am selben Tag
        bleiben mehrfach importierbar)."""
        dates = [line.value_date for line in lines if line.value_date is not None]
        if not dates:
            return {}
        rows = (
            await self.session.execute(
                select(
                    BankStatementLine.value_date,
                    BankStatementLine.amount,
                    BankStatementLine.end_to_end_id,
                    BankStatementLine.purpose,
                    BankStatementLine.counterparty_iban,
                ).where(
                    BankStatementLine.account_id == account_id,
                    BankStatementLine.value_date >= min(dates),
                    BankStatementLine.value_date <= max(dates),
                )
            )
        ).all()
        known: dict[tuple[str, str], int] = {}
        for value_date, amount, e2e, purpose, cp_iban in rows:
            fp = _Fingerprint(
                value_date=value_date,
                amount=amount,
                end_to_end=e2e,
                purpose_key=dedup.canonical_purpose_key(purpose),
                counterparty_iban=cp_iban,
            )
            for key in _fingerprint_keys(fp):
                known[key] = known.get(key, 0) + 1
        return known

    @staticmethod
    def _consume_fingerprint(
        known: dict[tuple[str, str], int], fp: _Fingerprint
    ) -> bool:
        """Eine Bestand-Übereinstimmung verbrauchen (Multiset) — ``True`` = Dublette.

        Übereinstimmung heißt: gleiche Wertstellung + Betrag **und** gleiche (nicht-leere)
        E2E-Referenz — oder, ohne E2E, gleicher (nicht-leerer) kanonischer Zweck + gleiche
        Gegen-IBAN. Zwei am selben Tag identische Zahlungen verbrauchen zwei Bestands-
        Einträge und bleiben damit korrekt getrennt."""
        for key in _fingerprint_keys(fp):
            count = known.get(key, 0)
            if count > 0:
                known[key] = count - 1
                return True
        return False

    async def _supersede_batch_totals(
        self, account_id: uuid.UUID, lines: list[statement.StatementLine]
    ) -> int:
        """Alte Gesamt-Zeilen aufgeteilter Sammelbuchungen entfernen (#fints-batch).

        Vor dem CAMT-Umstieg staged der MT940-Abruf eine Sammelbuchung als EINE Zeile
        („DATEI-NR. … ANZAHL …", Gesamtbetrag). Kommen jetzt die Einzelumsätze derselben
        Buchung (gleiche Wertstellung, Teilbeträge = Gesamtbetrag), wäre beides zusammen
        doppelt. Ersetzt werden nur **ungebuchte** (unmatched/suggested) Gesamt-Zeilen,
        deren Zweck das Sammel-Muster trägt; gebuchte/ignorierte bleiben unangetastet."""
        totals: set[tuple[date | None, Decimal]] = set()
        for line in lines:
            if line.raw.get("batch") != "true":
                continue
            try:
                total = Decimal(line.raw.get("batch_total", ""))
            except InvalidOperation:
                continue
            totals.add((line.value_date, total))
        if not totals:
            return 0
        superseded = 0
        for value_date, total in totals:
            candidates = (
                await self.session.execute(
                    select(BankStatementLine.id, BankStatementLine.purpose).where(
                        BankStatementLine.account_id == account_id,
                        BankStatementLine.value_date == value_date,
                        BankStatementLine.amount == total,
                        BankStatementLine.match_state.in_(("unmatched", "suggested")),
                    )
                )
            ).all()
            stale = [
                line_id
                for line_id, purpose in candidates
                if "DATEINR" in dedup.canonical_purpose_key(purpose)
            ]
            if not stale:
                continue
            await self.session.execute(
                delete(BankStatementLine).where(BankStatementLine.id.in_(stale))
            )
            superseded += len(stale)
        return superseded

    # ------------------------------------------------------------- suggestion
    async def _suggest(
        self, line: statement.StatementLine
    ) -> tuple[uuid.UUID | None, uuid.UUID | None]:
        """Vorschlag (Kostenstelle, bestehende Buchung) für einen Umsatz ermitteln."""
        kind = "income" if line.amount > 0 else "expense"
        amount = abs(line.amount)
        # Kandidaten: gleicher Betrag + Art, noch nicht zugeordnet.
        allocated = select(BankAllocation.expense_id)
        rows = (
            await self.session.execute(
                select(BudgetExpense)
                .where(
                    BudgetExpense.amount == amount,
                    BudgetExpense.kind == kind,
                    BudgetExpense.id.not_in(allocated),
                    # Nur Top-Level-Buchungen als Reconcile-Kandidaten (#subbookings-review):
                    # eine Unterbuchung darf nicht eigenständig einem Umsatz zugeordnet werden.
                    BudgetExpense.parent_expense_id.is_(None),
                )
                # Deterministische Kandidaten-Reihenfolge (#fints-review): ohne ORDER BY
                # entschiede die DB-Zeilenfolge bei gleichwertigen Treffern.
                .order_by(BudgetExpense.created_at, BudgetExpense.id)
                .limit(50)
            )
        ).scalars().all()
        candidates = [
            match.ExpenseCandidate(
                expense_id=e.id,
                budget_id=e.budget_id,
                amount=e.amount,
                when=e.payment_date or e.invoice_date or e.created_at.date(),
                reference=e.reference_number,
            )
            for e in rows
        ]
        result = match.best_match(
            line_amount=line.amount,
            line_when=line.value_date or line.booking_date,
            line_ref=line.reference,
            line_e2e=line.end_to_end_id,
            candidates=candidates,
        )
        if result.expense_id is not None:
            return result.budget_id, result.expense_id  # type: ignore[return-value]
        # Kein Buchungstreffer → Kostenstelle aus dem Gegen-IBAN-Gedächtnis vorschlagen.
        budget_id = await self._memory_budget(line.counterparty_iban)
        return budget_id, None

    async def _memory_budget(self, counterparty_iban: str | None) -> uuid.UUID | None:
        if not counterparty_iban:
            return None
        return await self.session.scalar(
            select(CounterpartyMemory.budget_id).where(
                CounterpartyMemory.counterparty_iban == counterparty_iban
            )
        )


def _line_fingerprint(line: statement.StatementLine) -> _Fingerprint:
    return _Fingerprint(
        value_date=line.value_date,
        amount=line.amount,
        end_to_end=line.end_to_end_id,
        purpose_key=dedup.canonical_purpose_key(line.purpose),
        counterparty_iban=line.counterparty_iban,
    )


def _fingerprint_keys(fp: _Fingerprint) -> list[tuple[str, str]]:
    """Vergleichs-Schlüssel eines Fingerprints: E2E-basiert und/oder Zweck+IBAN-basiert.

    Beide setzen Wertstellung + Betrag voraus; ohne Wertstellung (vorgemerkte Umsätze)
    findet KEIN Inhalts-Vergleich statt (zu unscharf) — dann greift nur der
    Idempotenz-Schlüssel."""
    if fp.value_date is None:
        return []
    base = f"{fp.value_date.isoformat()}|{fp.amount}"
    keys: list[tuple[str, str]] = []
    if fp.end_to_end:
        keys.append((base, f"e2e:{fp.end_to_end}"))
    elif fp.purpose_key:
        keys.append((base, f"pp:{fp.purpose_key}|{fp.counterparty_iban or ''}"))
    return keys
