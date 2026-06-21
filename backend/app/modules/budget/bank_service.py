"""FinTS-Bankabgleich (#fints) — Sync, Datei-Import, Staging, Abgleich.

Bindeglied zwischen :mod:`fints_client` (Live-Abruf, Option A) / :mod:`bank_import`
(Datei-Import, Option D), dem :mod:`bank_match`-Vorschlag und der Buchung. Gestagete
Umsätze (``bank_statement_line``) werden idempotent eingespielt; der Schatzmeister
bestätigt sie im Review-Dialog → daraus entsteht eine ``budget_expense`` (über
:class:`BudgetTreeService.book_expense`, inkl. dessen Validierung + Audit) und eine
``bank_allocation`` (Umsatz ↔ Buchung).

Die PIN wird **verschlüsselt** geladen und nur im Speicher entschlüsselt; der pausierte
TAN-Dialog liegt verschlüsselt + kurzlebig in ``bank_sync_session`` (security.md).
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.budget import bank_import, bank_match, fints_client
from app.modules.budget.fints_client import FintsError
from app.modules.budget.tree_models import (
    Account,
    BankAllocation,
    BankStatementLine,
    BankSyncSession,
    Budget,
    BudgetExpense,
    CounterpartyMemory,
)
from app.modules.budget.tree_schemas import (
    BankImportResult,
    BankSyncResult,
    ConfirmLineRequest,
    ExpenseCreate,
    ExpenseOut,
    StatementLineOut,
)
from app.modules.budget.tree_service import BudgetTreeService
from app.settings import Settings, get_settings
from app.shared.crypto import SecretCryptoError, decrypt_secret, encrypt_secret
from app.shared.errors import NotFoundError, ServiceUnavailableError, ValidationProblem

# Obergrenze für die Zeilenzahl eines Imports/Abrufs (Anti-DoS): ein 10-MiB-MT940 kann
# zehntausende Umsätze tragen; jede Zeile macht im Staging 1-2 Queries (#fints-review).
_MAX_STATEMENT_LINES = 10_000

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.budget.fints_client import FintsOutcome


class BankService:
    """FinTS-/Datei-gestützter Kontoabgleich (an eine Session gebunden)."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        settings: Settings | None = None,
        actor: str | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.actor = actor

    # ----------------------------------------------------------------- helpers
    def _require_enabled(self) -> str:
        """FinTS-Verschlüsselungs-Schlüssel oder 503 (Feature aus)."""
        key = self.settings.fints_enc_key
        if not key:
            raise ServiceUnavailableError("FinTS is not configured (no encryption key set).")
        return key

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
    def _line_out(line: BankStatementLine, suggested_path_key: str | None) -> StatementLineOut:
        return StatementLineOut(
            id=line.id,
            accountId=line.account_id,
            amount=line.amount,
            kind="income" if line.amount > 0 else "expense",
            currency=line.currency,
            bookingDate=line.booking_date,
            valueDate=line.value_date,
            purpose=line.purpose,
            counterpartyName=line.counterparty_name,
            counterpartyIban=line.counterparty_iban,
            endToEndId=line.end_to_end_id,
            reference=line.reference,
            matchState=line.match_state,  # type: ignore[arg-type]
            suggestedBudgetId=line.suggested_budget_id,
            suggestedPathKey=suggested_path_key,
            suggestedExpenseId=line.suggested_expense_id,
            createdAt=line.created_at,
        )

    # --------------------------------------------------------------- FinTS sync
    def _credentials(self, acc: Account) -> fints_client.FintsCredentials:
        """Verbindungs-/Login-Daten eines Kontos lesen, PIN entschlüsseln (nur im Speicher)."""
        if not (
            acc.fints_endpoint
            and acc.fints_blz
            and acc.fints_login
            and acc.fints_pin_encrypted
        ):
            raise ValidationProblem(
                "Account has no complete FinTS configuration.",
                code="fints_not_configured",
            )
        key = self._require_enabled()
        try:
            pin = decrypt_secret(acc.fints_pin_encrypted, key=key)
        except SecretCryptoError as exc:
            raise ValidationProblem(
                "Stored FinTS PIN could not be decrypted — re-enter it.",
                code="fints_pin_undecryptable",
            ) from exc
        return fints_client.FintsCredentials(
            endpoint=acc.fints_endpoint,
            blz=acc.fints_blz,
            login=acc.fints_login,
            pin=pin,
            account_iban=acc.iban or None,
            product_id=self.settings.fints_product_id,
            tan_mechanism=acc.fints_tan_mechanism,
            state=self._decode_state(acc.fints_state, key=key),
        )

    @staticmethod
    def _decode_state(stored: str | None, *, key: str) -> bytes | None:
        """Persistierten FinTS-Client-Zustand entschlüsseln → Bytes (sonst ``None``).

        Ein nicht entschlüsselbarer Zustand (Key-Rotation/Korruption) wird wie »kein
        Zustand« behandelt → der nächste Sync erzwingt einfach eine frische SCA."""
        if not stored:
            return None
        try:
            return decrypt_secret(stored, key=key).encode("latin-1")
        except SecretCryptoError:
            return None

    async def sync_account(self, account_id: uuid.UUID) -> BankSyncResult:
        """Schritt 1 (#fints): FinTS-Sync starten → Umsätze stagen **oder** TAN anfordern."""
        acc = await self._account_or_404(account_id)
        creds = self._credentials(acc)
        start = datetime.now(UTC).date() - timedelta(days=self.settings.fints_max_days)
        try:
            outcome = fints_client.start_sync(creds, start_date=start)
        except FintsError as exc:
            raise ServiceUnavailableError(f"FinTS sync failed: {exc}") from exc
        return await self._handle_outcome(acc, outcome)

    async def submit_tan(
        self, account_id: uuid.UUID, session_token: uuid.UUID, tan: str
    ) -> BankSyncResult:
        """Schritt 2 (#fints): pausierten Dialog mit TAN fortsetzen (leer = decoupled-Poll)."""
        acc = await self._account_or_404(account_id)
        pending = await self._load_session(session_token, account_id)
        creds = self._credentials(acc)
        creds.tan_mechanism = pending.tan_mechanism
        try:
            outcome = fints_client.submit_tan(creds, pending, tan)
        except FintsError as exc:
            raise ServiceUnavailableError(f"FinTS TAN submission failed: {exc}") from exc
        if outcome.status == "needs_tan":
            # decoupled noch nicht freigegeben → Sitzung aktualisieren, erneut anfordern.
            # Commit nötig: get_session committet NICHT automatisch, sonst ginge der
            # aufgefrischte Dialog-Zustand/TTL beim Request-Ende verloren (#fints-review).
            await self._store_session(acc.id, outcome, token=session_token)
            await self.session.commit()
            return self._needs_tan_result(acc.id, session_token, outcome)
        await self._delete_session(session_token)
        return await self._handle_outcome(acc, outcome)

    async def _handle_outcome(self, acc: Account, outcome: FintsOutcome) -> BankSyncResult:
        """``done`` → Zustand sichern + Umsätze stagen; ``needs_tan`` → Sitzung anlegen."""
        if outcome.status == "needs_tan":
            token = uuid.uuid4()
            await self._store_session(acc.id, outcome, token=token)
            await self.session.commit()
            return self._needs_tan_result(acc.id, token, outcome)

        if outcome.new_state is not None:
            # Client-Zustand (system_id/Dialog-State, SCA-Fenster) **verschlüsselt** ablegen
            # — wie die PIN; nie im Klartext (security.md, #fints-review).
            acc.fints_state = encrypt_secret(
                outcome.new_state.decode("latin-1"), key=self._require_enabled()
            )
        if outcome.tan_mechanism:
            acc.fints_tan_mechanism = outcome.tan_mechanism
        acc.fints_last_sync_at = datetime.now(UTC)
        imported, duplicates = await self._stage_lines(acc, outcome.lines)
        await self._audit(
            AuditAction.BANK_SYNC,
            target_id=str(acc.id),
            data={"imported": imported, "duplicates": duplicates, "source": "fints"},
        )
        await self.session.commit()
        return BankSyncResult(
            status="done", accountId=acc.id, imported=imported, duplicates=duplicates
        )

    @staticmethod
    def _needs_tan_result(
        account_id: uuid.UUID, token: uuid.UUID, outcome: FintsOutcome
    ) -> BankSyncResult:
        return BankSyncResult(
            status="needs_tan",
            accountId=account_id,
            sessionToken=token,
            challenge=outcome.challenge,
            challengeHtml=outcome.challenge_html,
            challengeImage=outcome.challenge_image,
            decoupled=outcome.decoupled,
        )

    # ----------------------------------------------------------- TAN sessions
    def _encode_outcome(self, outcome: FintsOutcome) -> str:
        """needs_tan-Zustand → verschlüsselter JSON-Blob (Bytes base64-kodiert)."""
        payload = {
            "client_data": base64.b64encode(outcome.client_data or b"").decode("ascii"),
            "dialog_data": base64.b64encode(outcome.dialog_data or b"").decode("ascii"),
            "tan_data": base64.b64encode(outcome.tan_data or b"").decode("ascii"),
            "tan_mechanism": outcome.tan_mechanism,
            "challenge": outcome.challenge,
            "challenge_html": outcome.challenge_html,
            "decoupled": outcome.decoupled,
        }
        return encrypt_secret(json.dumps(payload), key=self._require_enabled())

    async def _store_session(
        self, account_id: uuid.UUID, outcome: FintsOutcome, *, token: uuid.UUID
    ) -> None:
        expires = datetime.now(UTC) + timedelta(
            seconds=self.settings.fints_tan_session_ttl_seconds
        )
        existing = await self.session.get(BankSyncSession, token)
        if existing is not None:
            existing.payload_encrypted = self._encode_outcome(outcome)
            existing.expires_at = expires
            return
        self.session.add(
            BankSyncSession(
                id=token,
                account_id=account_id,
                payload_encrypted=self._encode_outcome(outcome),
                expires_at=expires,
            )
        )

    async def _load_session(
        self, token: uuid.UUID, account_id: uuid.UUID
    ) -> FintsOutcome:
        from app.modules.budget.fints_client import FintsOutcome

        row = await self.session.get(BankSyncSession, token)
        if row is None or row.account_id != account_id:
            raise NotFoundError("TAN session not found")
        if row.expires_at < datetime.now(UTC):
            await self._delete_session(token)
            await self.session.commit()
            raise ValidationProblem(
                "TAN session expired — start the sync again.", code="fints_tan_expired"
            )
        data = json.loads(decrypt_secret(row.payload_encrypted, key=self._require_enabled()))
        return FintsOutcome(
            status="needs_tan",
            tan_mechanism=data.get("tan_mechanism"),
            client_data=base64.b64decode(data["client_data"]),
            dialog_data=base64.b64decode(data["dialog_data"]),
            tan_data=base64.b64decode(data["tan_data"]),
            challenge=data.get("challenge"),
            challenge_html=data.get("challenge_html"),
            decoupled=bool(data.get("decoupled")),
        )

    async def _delete_session(self, token: uuid.UUID) -> None:
        await self.session.execute(
            delete(BankSyncSession).where(BankSyncSession.id == token)
        )

    # --------------------------------------------------------- file import (D)
    async def import_file(
        self, account_id: uuid.UUID, data: bytes, *, filename: str | None
    ) -> BankImportResult:
        """Option D (#fints): CAMT.053/MT940-Datei parsen + Umsätze stagen."""
        acc = await self._account_or_404(account_id)
        max_bytes = self.settings.attachment_max_bytes
        if len(data) > max_bytes:
            raise ValidationProblem(f"File exceeds {max_bytes} bytes.", code="file_too_large")
        try:
            lines = bank_import.parse_statement(data, filename=filename)
        except bank_import.StatementParseError as exc:
            raise ValidationProblem(
                "File is neither valid CAMT.053 nor MT940.", code="bank_statement_unparseable"
            ) from exc
        imported, duplicates = await self._stage_lines(acc, lines)
        await self._audit(
            AuditAction.BANK_STATEMENT_IMPORT,
            target_id=str(acc.id),
            data={"imported": imported, "duplicates": duplicates, "source": "file"},
        )
        await self.session.commit()
        return BankImportResult(accountId=acc.id, imported=imported, duplicates=duplicates)

    # ---------------------------------------------------------------- staging
    async def _stage_lines(
        self, acc: Account, lines: list[bank_import.StatementLine]
    ) -> tuple[int, int]:
        """Umsätze idempotent einspielen (``ON CONFLICT DO NOTHING``) + Vorschläge setzen.

        Liefert ``(neu, dubletten)``."""
        if len(lines) > _MAX_STATEMENT_LINES:
            raise ValidationProblem(
                f"Statement has too many transactions (>{_MAX_STATEMENT_LINES}).",
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
        bank_import.assign_keys(scope, lines)
        imported = 0
        for line in lines:
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
        return imported, len(lines) - imported

    async def _suggest(
        self, line: bank_import.StatementLine
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
                )
                .limit(50)
            )
        ).scalars().all()
        candidates = [
            bank_match.ExpenseCandidate(
                expense_id=e.id,
                budget_id=e.budget_id,
                amount=e.amount,
                when=e.payment_date or e.invoice_date or e.created_at.date(),
                reference=e.reference_number,
            )
            for e in rows
        ]
        match = bank_match.best_match(
            line_amount=line.amount,
            line_when=line.value_date or line.booking_date,
            line_ref=line.reference,
            line_e2e=line.end_to_end_id,
            candidates=candidates,
        )
        if match.expense_id is not None:
            return match.budget_id, match.expense_id  # type: ignore[return-value]
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

    # -------------------------------------------------------------- listing
    async def list_lines(
        self, *, account_id: uuid.UUID | None, state: str | None
    ) -> list[StatementLineOut]:
        """Gestagete Umsätze auflisten (optional je Konto / Status), neueste zuerst."""
        stmt = select(BankStatementLine)
        if account_id is not None:
            stmt = stmt.where(BankStatementLine.account_id == account_id)
        if state is not None:
            stmt = stmt.where(BankStatementLine.match_state == state)
        stmt = stmt.order_by(
            BankStatementLine.booking_date.desc().nullslast(),
            BankStatementLine.created_at.desc(),
        )
        rows = (await self.session.scalars(stmt)).all()
        paths = await self._path_keys(
            {r.suggested_budget_id for r in rows if r.suggested_budget_id}
        )
        return [
            self._line_out(
                r, paths.get(r.suggested_budget_id) if r.suggested_budget_id else None
            )
            for r in rows
        ]

    async def _path_keys(self, budget_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
        if not budget_ids:
            return {}
        rows = (
            await self.session.execute(
                select(Budget.id, Budget.path_key).where(Budget.id.in_(budget_ids))
            )
        ).all()
        return {bid: pk for bid, pk in rows}

    # ------------------------------------------------------------- confirm
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

        # Ziel **vor** dem Claim validieren, damit der Claim nur erfolgt, wenn das Buchen
        # auch durchgeht (minimiert das Orphan-Fenster: matched ohne Buchung).
        expense: BudgetExpense | None = None
        if payload.match_expense_id is not None:
            expense = await self.session.get(BudgetExpense, payload.match_expense_id)
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
                description = payload.description or self._default_description(line)
                created = await tree.book_expense(
                    ExpenseCreate(
                        amount=amount,
                        description=description,
                        kind=kind,  # type: ignore[arg-type]
                        budgetId=payload.budget_id,
                        fiscalYearId=payload.fiscal_year_id,
                        correspondent=line.counterparty_name,
                        paymentDate=line.value_date or line.booking_date,
                        referenceNumber=line.end_to_end_id or line.reference,
                        paymentMethod="ueberweisung",
                    ),
                    actor=self.actor or "",
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
                await self._remember_counterparty(line.counterparty_iban, payload.budget_id)
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
    def _default_description(line: BankStatementLine) -> str:
        parts = [p for p in (line.counterparty_name, line.purpose) if p]
        return " — ".join(parts) if parts else "Bankumsatz"

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
        if line.match_state == "matched":
            # Ein gebuchter Umsatz (mit Expense + Allocation) darf nicht still auf
            # 'ignored' gekippt werden — das würde Reconcile-Status vom Ledger entkoppeln.
            raise ValidationProblem(
                "A matched statement line cannot be ignored.", code="line_already_matched"
            )
        line.match_state = "ignored"
        await self._audit(AuditAction.BANK_LINE_IGNORE, target_id=str(line.id))
        await self.session.commit()
