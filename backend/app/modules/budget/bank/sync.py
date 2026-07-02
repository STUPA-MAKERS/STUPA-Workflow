"""FinTS-Sync-Orchestrierung: Abruf starten, TAN fortsetzen, Sitzung verwalten (#fints).

Die PIN wird **verschlüsselt** geladen und nur im Speicher entschlüsselt; der pausierte
TAN-Dialog liegt verschlüsselt + kurzlebig in ``bank_sync_session`` (security.md).
Erbt den Staging-Pfad (:class:`~.staging.StagingOps`) — ein erfolgreicher Sync spielt
die Umsätze direkt ein.
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete

from app.modules.audit.actions import AuditAction
from app.modules.budget.bank import client as fints_client
from app.modules.budget.bank.client import (
    FintsAuthRejectedError,
    FintsBankLockedError,
    FintsError,
    FintsOutcome,
)
from app.modules.budget.bank.staging import StagingOps
from app.modules.budget.tree_models import Account, AccountFintsCredential, BankSyncSession
from app.modules.budget.tree_schemas import BankSyncResult
from app.shared.crypto import SecretCryptoError, decrypt_secret, encrypt_secret
from app.shared.errors import (
    ConflictError,
    NotFoundError,
    ServiceUnavailableError,
    ValidationProblem,
)


class SyncOps(StagingOps):
    """FinTS-Live-Abruf (Option A) inkl. SCA-/TAN-Sitzungs-Handling."""

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
            # #fints-review) — der Client hat ihn bereits serverseitig geloggt.
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
        imported, duplicates, superseded = await self._stage_lines(acc, outcome.lines)
        await self._audit(
            AuditAction.BANK_SYNC,
            target_id=str(acc.id),
            data={
                "imported": imported,
                "duplicates": duplicates,
                "superseded": superseded,
                "source": "fints",
            },
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
