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

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.budget import bank_import, bank_match, fints_client
from app.modules.budget.fints_client import (
    FintsAuthRejectedError,
    FintsBankLockedError,
    FintsError,
)
from app.modules.budget.tree_models import (
    Account,
    AccountFintsCredential,
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
    FintsCredentialIn,
    FintsCredentialStatus,
    StatementLineOut,
)
from app.modules.budget.tree_service import BudgetTreeService
from app.settings import Settings, get_settings
from app.shared.crypto import SecretCryptoError, decrypt_secret, encrypt_secret
from app.shared.errors import (
    ConflictError,
    NotFoundError,
    ServiceUnavailableError,
    ValidationProblem,
)
from app.shared.paging import Page

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
    def _apply_balance(acc: Account, balance: bank_import.StatementBalance | None) -> None:
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
        # die Rohfelder ein sauberes Ergebnis; CAMT-Roh trägt sie nicht → Fallback auf die Spalte.
        name, iban = bank_import.resolve_counterparty(line.raw_payload, credit=line.amount > 0)
        if not name and not iban:
            # Fallback auf die gespeicherte Spalte (CAMT/alt) — Platzhalter trotzdem verwerfen.
            name = bank_import.clean_counterparty_name(line.counterparty_name)
            iban = line.counterparty_iban
        purpose = bank_import.resolve_purpose(line.raw_payload)
        if purpose is None:
            purpose = line.purpose
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

    # ------------------------------------------------------- personal credentials
    @staticmethod
    def _credential_status(
        acc: Account, cred: AccountFintsCredential | None
    ) -> FintsCredentialStatus:
        return FintsCredentialStatus(
            configured=bool(acc.fints_endpoint and acc.fints_blz),
            hasCredential=cred is not None,
            fintsLogin=cred.fints_login if cred else None,
            fintsLastSyncAt=cred.fints_last_sync_at if cred else None,
            fintsLockedUntil=cred.fints_locked_until if cred else None,
        )

    async def credential_status(self, account_id: uuid.UUID) -> FintsCredentialStatus:
        """Verbindungs-Status des Buchers für ein Konto (#fints-percred): ist das Konto
        FinTS-fähig und hat *dieser* Nutzer schon eigene Zugangsdaten hinterlegt?"""
        acc = await self._account_or_404(account_id)
        cred = await self.session.scalar(
            select(AccountFintsCredential).where(
                AccountFintsCredential.account_id == account_id,
                AccountFintsCredential.principal_id == self._require_principal(),
            )
        )
        return self._credential_status(acc, cred)

    async def set_credential(
        self, account_id: uuid.UUID, payload: FintsCredentialIn
    ) -> FintsCredentialStatus:
        """Persönliche Zugangsdaten des Buchers (Login + PIN) anlegen/ersetzen (#fints-percred).

        Erstes Verbinden im Buchungs-Tab. PIN wird **verschlüsselt** abgelegt; bei einer
        Änderung wird der bisherige SCA-Zustand/TAN-Mechanismus verworfen (neue Daten →
        frische SCA). Setzt voraus, dass der Admin die Bank-Verbindung (Endpunkt + BLZ) am
        Konto gesetzt hat."""
        acc = await self._account_or_404(account_id)
        if not (acc.fints_endpoint and acc.fints_blz):
            raise ValidationProblem(
                "Account has no FinTS connection configured.",
                code="fints_not_configured",
            )
        key = self._require_enabled()
        pid = self._require_principal()
        pin_encrypted = encrypt_secret(payload.fints_pin, key=key)
        cred = await self.session.scalar(
            select(AccountFintsCredential).where(
                AccountFintsCredential.account_id == account_id,
                AccountFintsCredential.principal_id == pid,
            )
        )
        if cred is None:
            cred = AccountFintsCredential(
                id=uuid.uuid4(),
                account_id=account_id,
                principal_id=pid,
                fints_login=payload.fints_login,
                fints_pin_encrypted=pin_encrypted,
            )
            self.session.add(cred)
        else:
            cred.fints_login = payload.fints_login
            cred.fints_pin_encrypted = pin_encrypted
            # Neue Zugangsdaten → bisheriger Dialog-Zustand ungültig (frische SCA).
            cred.fints_state = None
            cred.fints_tan_mechanism = None
        # Audit **ohne** Login/PIN (security.md §4) — der ``actor`` identifiziert den Bucher.
        await self._audit(AuditAction.BANK_CREDENTIAL_SET, target_id=str(account_id))
        await self.session.commit()
        return self._credential_status(acc, cred)

    async def delete_credential(self, account_id: uuid.UUID) -> None:
        """Persönliche Zugangsdaten des Buchers für ein Konto löschen (#fints-percred)."""
        pid = self._require_principal()
        row = (
            await self.session.execute(
                delete(AccountFintsCredential)
                .where(
                    AccountFintsCredential.account_id == account_id,
                    AccountFintsCredential.principal_id == pid,
                )
                .returning(AccountFintsCredential.id)
            )
        ).first()
        if row is None:
            raise NotFoundError("no FinTS credential to delete")
        await self._audit(AuditAction.BANK_CREDENTIAL_DELETE, target_id=str(account_id))
        await self.session.commit()

    # --------------------------------------------------------------- FinTS sync
    def _credentials(
        self, acc: Account, cred: AccountFintsCredential
    ) -> fints_client.FintsCredentials:
        """Bank-Verbindung (Konto) + persönliche Login-Daten (Credential) zusammenführen,
        PIN entschlüsseln (nur im Speicher, #fints-percred)."""
        if not (acc.fints_endpoint and acc.fints_blz):
            raise ValidationProblem(
                "Account has no FinTS connection configured.",
                code="fints_not_configured",
            )
        key = self._require_enabled()
        try:
            pin = decrypt_secret(cred.fints_pin_encrypted, key=key)
        except SecretCryptoError as exc:
            raise ValidationProblem(
                "Stored FinTS PIN could not be decrypted — re-enter it.",
                code="fints_pin_undecryptable",
            ) from exc
        return fints_client.FintsCredentials(
            endpoint=acc.fints_endpoint,
            blz=acc.fints_blz,
            login=cred.fints_login,
            pin=pin,
            account_iban=acc.iban or None,
            product_id=self.settings.fints_product_id,
            tan_mechanism=cred.fints_tan_mechanism,
            state=self._decode_state(cred.fints_state, key=key),
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

    def _guard_not_locked(self, cred: AccountFintsCredential) -> None:
        """Sync ablehnen, solange ein Sperr-Cooldown läuft (#fints-review).

        Nach einer Bank-Sperre/Signatur-Ablehnung zahlt **jeder** weitere Login auf das Bank-
        Fehlversuchskonto ein und kann die Sperre verschärfen. Der serverseitige Cooldown ist
        die maßgebliche Bremse (das FE deaktiviert den Button nur zusätzlich)."""
        until = cred.fints_locked_until
        if until is None:
            return
        now = datetime.now(UTC)
        if until > now:
            raise ConflictError(
                "FinTS access is locked — do not retry until the cooldown elapses.",
                code="fints_bank_locked",
                headers={"Retry-After": str(int((until - now).total_seconds()))},
            )

    async def _record_lock(self, cred: AccountFintsCredential) -> None:
        """Sperr-Cooldown setzen + persistieren (#fints-review) — Folgeversuche werden bis zum
        Ablauf von :meth:`_guard_not_locked` abgewiesen."""
        cred.fints_locked_until = datetime.now(UTC) + timedelta(
            minutes=self.settings.fints_lock_cooldown_minutes
        )
        await self.session.commit()

    @staticmethod
    def _lock_code(exc: FintsError) -> str:
        return (
            "fints_bank_locked"
            if isinstance(exc, FintsBankLockedError)
            else "fints_auth_rejected"
        )

    async def sync_account(self, account_id: uuid.UUID) -> BankSyncResult:
        """Schritt 1 (#fints): FinTS-Sync starten → Umsätze stagen **oder** TAN anfordern."""
        acc = await self._account_or_404(account_id)
        cred = await self._load_credential(account_id)
        self._guard_not_locked(cred)
        await self._purge_expired_sessions()
        creds = self._credentials(acc, cred)
        self._revalidate_endpoint(creds.endpoint)
        start = datetime.now(UTC).date() - timedelta(days=self.settings.fints_max_days)
        try:
            outcome = fints_client.start_sync(creds, start_date=start)
        except (FintsBankLockedError, FintsAuthRejectedError) as exc:
            # Bank hat gesperrt/abgelehnt → Cooldown setzen und als 409 (NICHT wiederholen)
            # melden, statt als generischer 503 (der zum erneuten Klick verleitet).
            await self._record_lock(cred)
            raise ConflictError(
                "FinTS access was rejected or locked by the bank — do not retry.",
                code=self._lock_code(exc),
            ) from exc
        except FintsError as exc:
            # Lib-/Bank-Fehlertext NICHT an den Client durchreichen (kann Sensibles tragen,
            # #fints-review) — fints_client hat ihn bereits serverseitig geloggt.
            raise ServiceUnavailableError(
                "FinTS sync failed.", code="fints_sync_failed"
            ) from exc
        return await self._handle_outcome(acc, cred, outcome)

    def _revalidate_endpoint(self, endpoint: str) -> None:
        """SSRF-Endpunkt **erneut zur Abruf-Zeit** prüfen (#fints-review).

        Die Validierung bei der Konto-Konfiguration allein genügt nicht: zwischen Setzen und
        Abruf kann der DNS-Eintrag auf eine interne IP umgebogen werden (Rebinding), und
        ``account.manage`` (setzt Endpunkt) ≠ ``budget.book`` (löst Sync aus). Hier erneut
        auflösen + gegen den SSRF-Guard prüfen verkürzt das Fenster drastisch. **Restrisiko**
        (von der Egress-Firewall abzufangen): ``python-fints`` löst beim Verbinden selbst noch
        einmal auf und folgt Redirects — IP-Pinning des Connects ist Folge-Arbeit."""
        try:
            fints_client.validate_fints_endpoint(endpoint)
        except ValueError as exc:
            raise ValidationProblem(
                "FinTS endpoint is not allowed.", code="fints_endpoint_blocked"
            ) from exc

    async def _purge_expired_sessions(self) -> None:
        """Abgelaufene TAN-Sitzungen global aufräumen (#fints-review) — sonst bleiben
        abgebrochene SCA-Dialoge (verschlüsselt) unbegrenzt liegen; der lazy Lösch-Pfad in
        :meth:`_claim_session` greift nur für genau das angefragte Token."""
        await self.session.execute(
            delete(BankSyncSession).where(BankSyncSession.expires_at < datetime.now(UTC))
        )

    async def submit_tan(
        self, account_id: uuid.UUID, session_token: uuid.UUID, tan: str
    ) -> BankSyncResult:
        """Schritt 2 (#fints): pausierten Dialog mit TAN fortsetzen (leer = decoupled-Poll)."""
        acc = await self._account_or_404(account_id)
        cred = await self._load_credential(account_id)
        self._guard_not_locked(cred)
        # Sitzung **atomar beanspruchen** (löschen) BEVOR der Netz-Call läuft (#fints-review):
        # ein zweiter, paralleler Submit mit demselben Token findet nichts mehr → kein Replay
        # des fortgesetzten Dialogs / kein Doppel-Audit. Schlägt der Call fehl, ist die Sitzung
        # weg und der Nutzer startet den Sync neu (TAN-Flows sind kurz).
        pending = await self._claim_session(session_token, account_id)
        creds = self._credentials(acc, cred)
        self._revalidate_endpoint(creds.endpoint)
        creds.tan_mechanism = pending.tan_mechanism
        # Bei Login-SCA holt submit_tan nach der TAN erst die Umsätze → Abruf-Fenster setzen
        # (wie beim Start-Sync); bei einer Daten-TAN ist das unschädlich (#fints login-SCA).
        creds.start_date = datetime.now(UTC).date() - timedelta(days=self.settings.fints_max_days)
        try:
            outcome = fints_client.submit_tan(creds, pending, tan)
        except (FintsBankLockedError, FintsAuthRejectedError) as exc:
            await self._record_lock(cred)
            raise ConflictError(
                "FinTS access was rejected or locked by the bank — do not retry.",
                code=self._lock_code(exc),
            ) from exc
        except FintsError as exc:
            raise ServiceUnavailableError(
                "FinTS TAN submission failed.", code="fints_tan_failed"
            ) from exc
        # Netz-Call lief durch (Login akzeptiert) → etwaigen Sperr-Cooldown aufheben.
        cred.fints_locked_until = None
        if outcome.status == "needs_tan":
            # decoupled noch nicht freigegeben → **neues** Token (das alte ist verbraucht,
            # nicht wiederverwendbar) anlegen und erneut anfordern.
            new_token = uuid.uuid4()
            await self._store_session(acc.id, outcome, token=new_token)
            await self.session.commit()
            return self._needs_tan_result(acc.id, new_token, outcome)
        return await self._handle_outcome(acc, cred, outcome)

    async def _handle_outcome(
        self, acc: Account, cred: AccountFintsCredential, outcome: FintsOutcome
    ) -> BankSyncResult:
        """``done`` → Zustand sichern + Umsätze stagen; ``needs_tan`` → Sitzung anlegen.

        SCA-Zustand/TAN-Methode/Last-Sync gehören dem **Bucher** (Credential), nicht dem Konto
        (#fints-percred)."""
        # Netz-Call lief durch (Login akzeptiert) → etwaigen Sperr-Cooldown aufheben.
        cred.fints_locked_until = None
        if outcome.status == "needs_tan":
            token = uuid.uuid4()
            await self._store_session(acc.id, outcome, token=token)
            await self.session.commit()
            return self._needs_tan_result(acc.id, token, outcome)

        if outcome.new_state is not None:
            # Client-Zustand (system_id/Dialog-State, SCA-Fenster) **verschlüsselt** ablegen
            # — wie die PIN; nie im Klartext (security.md, #fints-review).
            cred.fints_state = encrypt_secret(
                outcome.new_state.decode("latin-1"), key=self._require_enabled()
            )
        if outcome.tan_mechanism:
            cred.fints_tan_mechanism = outcome.tan_mechanism
        cred.fints_last_sync_at = datetime.now(UTC)
        self._apply_balance(acc, outcome.balance)
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
            "tan_for_login": outcome.tan_for_login,
        }
        return encrypt_secret(json.dumps(payload), key=self._require_enabled())

    async def _store_session(
        self, account_id: uuid.UUID, outcome: FintsOutcome, *, token: uuid.UUID
    ) -> None:
        # Token sind immer frisch (initialer ``needs_tan`` und decoupled-Re-Poll erzeugen je
        # ein neues UUID) → reines Insert, kein Update-Pfad nötig (#fints-review).
        expires = datetime.now(UTC) + timedelta(
            seconds=self.settings.fints_tan_session_ttl_seconds
        )
        self.session.add(
            BankSyncSession(
                id=token,
                account_id=account_id,
                principal_id=self._require_principal(),
                payload_encrypted=self._encode_outcome(outcome),
                expires_at=expires,
            )
        )

    async def _claim_session(
        self, token: uuid.UUID, account_id: uuid.UUID
    ) -> FintsOutcome:
        """TAN-Sitzung **atomar** entnehmen: per ``DELETE … RETURNING`` löschen + sofort
        committen, damit ein paralleler Submit sie nicht erneut laden kann (Anti-Replay,
        #fints-review). Auf den startenden Bucher gescopt (#fints-percred) — ein anderer
        Principal kann eine fremde TAN-Sitzung nicht einreichen. Abgelaufen/nicht
        entschlüsselbar → 422 (Sync neu starten), nicht 500."""
        from app.modules.budget.fints_client import FintsOutcome

        row = (
            await self.session.execute(
                delete(BankSyncSession)
                .where(
                    BankSyncSession.id == token,
                    BankSyncSession.account_id == account_id,
                    BankSyncSession.principal_id == self._require_principal(),
                )
                .returning(
                    BankSyncSession.payload_encrypted, BankSyncSession.expires_at
                )
            )
        ).first()
        # Claim sofort sichtbar machen → ein zeitgleicher zweiter Submit findet nichts mehr.
        await self.session.commit()
        if row is None:
            raise NotFoundError("TAN session not found")
        payload_encrypted, expires_at = row
        if expires_at < datetime.now(UTC):
            raise ValidationProblem(
                "TAN session expired — start the sync again.", code="fints_tan_expired"
            )
        try:
            data = json.loads(decrypt_secret(payload_encrypted, key=self._require_enabled()))
        except SecretCryptoError as exc:
            raise ValidationProblem(
                "TAN session could not be decrypted — start the sync again.",
                code="fints_tan_expired",
            ) from exc
        return FintsOutcome(
            status="needs_tan",
            tan_mechanism=data.get("tan_mechanism"),
            client_data=base64.b64decode(data["client_data"]),
            dialog_data=base64.b64decode(data["dialog_data"]),
            tan_data=base64.b64decode(data["tan_data"]),
            challenge=data.get("challenge"),
            challenge_html=data.get("challenge_html"),
            decoupled=bool(data.get("decoupled")),
            tan_for_login=bool(data.get("tan_for_login")),
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
            lines, balance = bank_import.parse_statement_full(data, filename=filename)
        except bank_import.StatementParseError as exc:
            raise ValidationProblem(
                "File is neither valid CAMT.053 nor MT940.", code="bank_statement_unparseable"
            ) from exc
        self._apply_balance(acc, balance)
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
    async def list_lines_paged(
        self,
        *,
        account_id: uuid.UUID | None,
        state: str | None,
        linked: bool | None = None,
        kind: str | None = None,
        q: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        sort: str | None = None,
        order: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Page[StatementLineOut]:
        """Gestagete Umsätze gefiltert + offset-paginiert (#fints-konten).

        Filter: ``account``, ``state``, ``kind`` (income = Betrag > 0, expense < 0), Datumsbereich
        (Valuta, sonst Buchungsdatum) und Volltext (``q``) über Gegenkonto/IBAN/Zweck. ``sort`` =
        ``date`` (Default) | ``amount``."""
        filters = []
        if account_id is not None:
            filters.append(BankStatementLine.account_id == account_id)
        if state is not None:
            filters.append(BankStatementLine.match_state == state)
        if linked is True:
            filters.append(BankStatementLine.match_state == "matched")
        elif linked is False:
            # „offen" = noch nicht gebucht (ungematcht/Vorschlag), ohne als irrelevant Markierte.
            filters.append(BankStatementLine.match_state.in_(("unmatched", "suggested")))
        if kind == "income":
            filters.append(BankStatementLine.amount > 0)
        elif kind == "expense":
            filters.append(BankStatementLine.amount < 0)
        eff_date = func.coalesce(BankStatementLine.value_date, BankStatementLine.booking_date)
        if date_from:
            filters.append(eff_date >= date_from)
        if date_to:
            filters.append(eff_date <= date_to)
        if q and q.strip():
            like = f"%{q.strip()}%"
            filters.append(
                or_(
                    BankStatementLine.counterparty_name.ilike(like),
                    BankStatementLine.counterparty_iban.ilike(like),
                    BankStatementLine.purpose.ilike(like),
                )
            )
        where = and_(*filters) if filters else None
        count_stmt = select(func.count()).select_from(BankStatementLine)
        if where is not None:
            count_stmt = count_stmt.where(where)
        total = await self.session.scalar(count_stmt)
        if sort == "amount":
            primary = (
                BankStatementLine.amount.asc()
                if order == "asc"
                else BankStatementLine.amount.desc()
            )
        else:
            primary = eff_date.asc().nullslast() if order == "asc" else eff_date.desc().nullslast()
        stmt = select(BankStatementLine)
        if where is not None:
            stmt = stmt.where(where)
        stmt = (
            stmt.order_by(primary, BankStatementLine.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = (await self.session.scalars(stmt)).all()
        paths = await self._path_keys(
            {r.suggested_budget_id for r in rows if r.suggested_budget_id}
        )
        items = [
            self._line_out(
                r, paths.get(r.suggested_budget_id) if r.suggested_budget_id else None
            )
            for r in rows
        ]
        return Page(items=items, total=total or 0, limit=limit, offset=offset)

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

        # Gegenkonto bereinigen (#fints): primär aus den SEPA-Rohfeldern (``raw_payload``:
        # ABWE+/ABWA+/IBAN+) neu ableiten — so bekommen auch VOR dem Parser-Fix gestagete Umsätze
        # (Name nur „KRZL", keine ?31-IBAN) beim Buchen sauberen Empfänger/IBAN. Liefert das nichts
        # (z. B. CAMT-/Datei-Import ohne GVC-Felder), die gespeicherten Werte (ggf. IBAN aus dem
        # Namen lösen) verwenden.
        clean_name, clean_iban = bank_import.mt940_counterparty(
            line.raw_payload or {}, credit=line.amount > 0
        )
        if not clean_name and not clean_iban:
            clean_name, clean_iban = bank_import.split_leading_iban(
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
        return bank_import.build_short_description(name, purpose)

    @staticmethod
    def _booking_note(
        line: BankStatementLine, kind: str, *, name: str | None, iban: str | None
    ) -> str | None:
        """Strukturierte Anmerkung (Empfänger/Absender · IBAN · Zweck · Buchung) zum Umsatz.
        ``name``/``iban`` sind bereits bereinigt (IBAN aus dem Namen gelöst, #fints).

        Die Sparkassen-Buchungsuhrzeit (``DATUM … UHR``) wurde beim Parsen nach
        ``raw_payload['booking_time']`` gelöst; CAMT/andere Banken liefern nur das Datum."""
        booking_time = (line.raw_payload or {}).get("booking_time")
        return bank_import.build_booking_note(
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
