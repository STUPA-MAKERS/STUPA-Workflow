"""Gestagete Umsätze bestätigen / ignorieren / lösen (#fints).

Der Schatzmeister bestätigt einen Umsatz im Review-Dialog → daraus entsteht eine
``budget_expense`` (über :meth:`BudgetTreeService.book_expense`, inkl. dessen Validierung
+ Audit) und eine ``bank_allocation`` (Umsatz ↔ Buchung).
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.modules.audit.actions import AuditAction
from app.modules.budget.bank import normalize
from app.modules.budget.bank.service_base import BankServiceBase
from app.modules.budget.tree.service import BudgetTreeService
from app.modules.budget.tree_models import (
    BankAllocation,
    BankStatementLine,
    BudgetExpense,
    CounterpartyMemory,
)
from app.modules.budget.tree_schemas import (
    ConfirmLineRequest,
    ExpenseCreate,
    ExpenseOut,
    StatementLineOut,
)
from app.shared.errors import NotFoundError, ValidationProblem


class ReconcileOps(BankServiceBase):
    """Bestätigen (buchen), Ignorieren und Lösen gestageter Umsätze."""

    async def confirm_line(self, line_id: uuid.UUID, payload: ConfirmLineRequest) -> ExpenseOut:
        """Umsatz bestätigen (#fints): neue Buchung anlegen **oder** an bestehende anhängen.

        Beide Wege erzeugen eine ``bank_allocation`` (Umsatz ↔ Buchung) und setzen den
        Umsatz auf ``matched``."""
        line = await self.session.get(BankStatementLine, line_id)
        if line is None:
            raise NotFoundError(f"statement line {line_id} not found")
        if line.match_state == "matched":
            raise ValidationProblem(
                "Statement line is already matched.", code="line_already_matched"
            )

        tree = BudgetTreeService(self.session, settings=self.settings, actor=self.actor)
        kind = "income" if line.amount > 0 else "expense"
        amount = abs(line.amount)
        if amount == 0:
            raise ValidationProblem(
                "A zero-amount transaction cannot be booked.", code="line_zero_amount"
            )

        # Gegenkonto bereinigen (#fints): primär aus den SEPA-Rohfeldern (``raw_payload``:
        # ABWE+/ABWA+/IBAN+) neu ableiten — so bekommen auch VOR dem Parser-Fix gestagete Umsätze
        # (Name nur „KRZL", keine ?31-IBAN) beim Buchen sauberen Empfänger/IBAN. Liefert das nichts
        # (z. B. CAMT-/Datei-Import ohne GVC-Felder), die gespeicherten Werte (ggf. IBAN aus dem
        # Namen lösen) verwenden.
        clean_name, clean_iban = normalize.mt940_counterparty(
            line.raw_payload or {}, credit=line.amount > 0
        )
        if not clean_name and not clean_iban:
            clean_name, clean_iban = normalize.split_leading_iban(
                line.counterparty_name, line.counterparty_iban
            )

        # Ziel **vor** dem Claim validieren, damit der Claim nur erfolgt, wenn das Buchen
        # auch durchgeht (minimiert das Orphan-Fenster: matched ohne Buchung).
        expense: BudgetExpense | None = None
        if payload.match_expense_id is not None:
            # ``with_for_update`` sperrt die Buchungszeile bis zum Commit (#fints-review):
            # ohne sie könnten zwei parallele Confirms unterschiedlicher Umsätze gegen
            # **dieselbe** Buchung beide am ``already``-Check vorbeikommen und je eine
            # Allocation anlegen (eine Zahlung doppelt abgeglichen) — der konditionale
            # Claim-UPDATE schützt nur je Umsatz-Zeile, nicht die geteilte Buchung.
            expense = await self.session.get(
                BudgetExpense, payload.match_expense_id, with_for_update=True
            )
            if expense is None:
                raise NotFoundError(f"expense {payload.match_expense_id} not found")
            if expense.kind != kind:
                raise ValidationProblem(
                    "Booking kind does not match the transaction direction.",
                    code="line_kind_mismatch",
                )
            if expense.amount != amount:
                raise ValidationProblem(
                    "Booking amount does not match the transaction amount.",
                    code="line_amount_mismatch",
                )
            if expense.account_id is not None and expense.account_id != line.account_id:
                raise ValidationProblem(
                    "Booking belongs to a different account than the statement line.",
                    code="line_account_mismatch",
                )
            already = await self.session.scalar(
                select(BankAllocation.id)
                .where(BankAllocation.expense_id == expense.id)
                .limit(1)
            )
            if already is not None:
                raise ValidationProblem(
                    "That booking is already reconciled with a transaction.",
                    code="expense_already_allocated",
                )

        # **Eine** Transaktion für Claim + Buchung + Allocation + Audit (#fints-review):
        # Der konditionale Claim-UPDATE (match_state != 'matched') hält die Zeile gesperrt,
        # bis ganz unten committet wird → nebenläufige Confirms blockieren und sehen danach
        # 'matched' (kein Doppel-Buchen). book_expense läuft mit ``commit=False``, sodass
        # ein Fehler an JEDER Stelle per rollback ALLES zurücknimmt — Claim **und** Buchung
        # (keine verwaiste Buchung, kein Doppel-Soll bei Retry).
        try:
            claimed = (
                await self.session.execute(
                    update(BankStatementLine)
                    .where(
                        BankStatementLine.id == line_id,
                        BankStatementLine.match_state != "matched",
                    )
                    .values(match_state="matched")
                    .returning(BankStatementLine.id)
                )
            ).first()
            if claimed is None:
                raise ValidationProblem(
                    "Statement line is already matched.", code="line_already_matched"
                )

            if expense is not None:
                expense_out = tree._expense_out(expense, None)
                expense_id = expense.id
            else:
                description = payload.description or self._default_description(
                    clean_name, line.purpose
                )
                created = await tree.book_expense(
                    ExpenseCreate(
                        amount=amount,
                        description=description,
                        kind=kind,  # type: ignore[arg-type]
                        budgetId=payload.budget_id,
                        fiscalYearId=payload.fiscal_year_id,
                        correspondent=clean_name,
                        note=self._booking_note(line, kind, name=clean_name, iban=clean_iban),
                        paymentDate=line.value_date or line.booking_date,
                        referenceNumber=line.end_to_end_id or line.reference,
                        paymentMethod="ueberweisung",
                    ),
                    actor=self.actor or "",
                    # Konto des Umsatzes auf die Buchung übernehmen (#fints) — kein manuelles Feld
                    # mehr, daher explizit hier durchgereicht.
                    account_id=line.account_id,
                    commit=False,  # gemeinsame Transaktion — der Commit unten ist der einzige
                )
                expense_out = created
                expense_id = created.id

            self.session.add(
                BankAllocation(
                    id=uuid.uuid4(),
                    statement_line_id=line.id,
                    expense_id=expense_id,
                    allocated_amount=amount,
                )
            )
            if payload.budget_id is not None:
                await self._remember_counterparty(clean_iban, payload.budget_id)
            await self._audit(
                AuditAction.BANK_LINE_RECONCILE,
                target_id=str(line.id),
                data={"expenseId": str(expense_id), "kind": kind, "amount": str(amount)},
            )
            await self.session.commit()
        except Exception:
            # Alles in einer Transaktion → ein Rollback nimmt Claim + Buchung gemeinsam
            # zurück; der Umsatz bleibt offen und kann sauber erneut bestätigt werden.
            await self.session.rollback()
            raise
        return expense_out

    @staticmethod
    def _default_description(name: str | None, purpose: str | None) -> str:
        """Kurzform-Beschreibung ``<Zweck> – <Name>`` (gleiches Format wie die kuratierten
        Bestandsbuchungen) — die volle, formatierte Beschreibung steht in der Anmerkung.
        ``name`` ist bereits bereinigt (IBAN abgespalten, #fints)."""
        return normalize.build_short_description(name, purpose)

    @staticmethod
    def _booking_note(
        line: BankStatementLine, kind: str, *, name: str | None, iban: str | None
    ) -> str | None:
        """Strukturierte Anmerkung (Empfänger/Absender · IBAN · Zweck · Buchung) zum Umsatz.
        ``name``/``iban`` sind bereits bereinigt (IBAN aus dem Namen gelöst, #fints).

        Die Sparkassen-Buchungsuhrzeit (``DATUM … UHR``) wurde beim Parsen nach
        ``raw_payload['booking_time']`` gelöst; CAMT/andere Banken liefern nur das Datum."""
        booking_time = (line.raw_payload or {}).get("booking_time")
        return normalize.build_booking_note(
            name=name,
            iban=iban,
            purpose=line.purpose,
            kind=kind,
            when=line.value_date or line.booking_date,
            booking_time=booking_time if isinstance(booking_time, str) else None,
        )

    async def _remember_counterparty(
        self, counterparty_iban: str | None, budget_id: uuid.UUID
    ) -> None:
        """Gegen-IBAN → Kostenstelle merken/aktualisieren (Vorschlag beim nächsten Mal)."""
        if not counterparty_iban:
            return
        stmt = (
            pg_insert(CounterpartyMemory)
            .values(id=uuid.uuid4(), counterparty_iban=counterparty_iban, budget_id=budget_id)
            .on_conflict_do_update(
                constraint="uq_counterparty_memory_iban",
                set_={"budget_id": budget_id},
            )
        )
        await self.session.execute(stmt)

    async def ignore_line(self, line_id: uuid.UUID) -> None:
        """Umsatz als irrelevant markieren (#fints) — bleibt erhalten (idempotenter Import)."""
        line = await self.session.get(BankStatementLine, line_id)
        if line is None:
            raise NotFoundError(f"statement line {line_id} not found")
        # Konditionaler Claim wie bei confirm_line (#fints-review): ein parallel frisch
        # gebuchter ('matched') Umsatz darf NICHT per ORM-Dirty-Flush auf 'ignored'
        # zurückgekippt werden — das entkoppelte den Reconcile-Status vom Ledger.
        claimed = (
            await self.session.execute(
                update(BankStatementLine)
                .where(
                    BankStatementLine.id == line_id,
                    BankStatementLine.match_state != "matched",
                )
                .values(match_state="ignored")
                .returning(BankStatementLine.id)
            )
        ).first()
        if claimed is None:
            raise ValidationProblem(
                "A matched statement line cannot be ignored.", code="line_already_matched"
            )
        await self._audit(AuditAction.BANK_LINE_IGNORE, target_id=str(line_id))
        await self.session.commit()

    async def unlink_line(self, line_id: uuid.UUID) -> StatementLineOut:
        """Zuordnung Umsatz↔Buchung lösen (#fints-konten): die ``bank_allocation`` entfernen und
        den Umsatz wieder auf ``unmatched`` setzen. Die **Buchung bleibt** bestehen (sie ist der
        Geld-Datensatz; nur die Bank-Verknüpfung wird gelöst)."""
        line = await self.session.get(BankStatementLine, line_id)
        if line is None:
            raise NotFoundError(f"statement line {line_id} not found")
        await self.session.execute(
            delete(BankAllocation).where(BankAllocation.statement_line_id == line_id)
        )
        line.match_state = "unmatched"
        await self._audit(AuditAction.BANK_LINE_UNLINK, target_id=str(line_id))
        await self.session.commit()
        # FE lädt die Liste nach dem Unlink neu (inkl. Vorschlag) → hier kein path-key nötig.
        return self._line_out(line, None)
