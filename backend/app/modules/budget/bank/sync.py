"""FinTS sync orchestration: start fetch, resume with TAN, manage sessions.

The PIN is loaded encrypted and decrypted only in memory; the paused TAN dialog
is stored encrypted and short-lived in ``bank_sync_session``. Inherits the
staging path (:class:`~.staging.StagingOps`) — a successful sync stages the
transactions directly.
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
    FintsAccountSelectionError,
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
    """FinTS live fetch incl. SCA/TAN session handling."""

    def _credentials(
        self, acc: Account, cred: AccountFintsCredential
    ) -> fints_client.FintsCredentials:
        """Merge bank connection (account) + personal login data (credential),
        decrypting the PIN in memory only."""
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
        """Decrypt the persisted FinTS client state to bytes (else ``None``).

        An undecryptable state (key rotation/corruption) is treated as "no state"
        — the next sync simply forces a fresh SCA."""
        if not stored:
            return None
        try:
            return decrypt_secret(stored, key=key).encode("latin-1")
        except SecretCryptoError:
            return None

    def _guard_not_locked(self, cred: AccountFintsCredential) -> None:
        """Reject the sync while a lock cooldown is running.

        After a bank lock/signature rejection, EVERY further login counts against
        the bank's failed-attempt account and can escalate the lock. The
        server-side cooldown is the authoritative brake (the frontend merely
        disables the button as well)."""
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
        """Set and persist the lock cooldown — follow-up attempts are rejected by
        :meth:`_guard_not_locked` until it elapses."""
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
        """Step 1: start the FinTS sync — stage transactions or request a TAN."""
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
            # Bank locked/rejected: set the cooldown and report as 409 (do NOT
            # retry) instead of a generic 503 that invites another click.
            await self._record_lock(cred)
            raise ConflictError(
                "FinTS access was rejected or locked by the bank — do not retry.",
                code=self._lock_code(exc),
            ) from exc
        except FintsAccountSelectionError as exc:
            # Ambiguous account (login has several, none matched the configured
            # IBAN): a config problem, not a bank error — 422 with a clear code so
            # the treasurer sets the IBAN, and NEVER a silently wrong fetch.
            raise ValidationProblem(
                "This account could not be matched at the bank — set its IBAN.",
                code="fints_account_ambiguous",
            ) from exc
        except FintsError as exc:
            # Do NOT pass the lib/bank error text to the client (may carry
            # sensitive data) — the client already logged it server-side.
            raise ServiceUnavailableError(
                "FinTS sync failed.", code="fints_sync_failed"
            ) from exc
        return await self._handle_outcome(acc, cred, outcome)

    def _revalidate_endpoint(self, endpoint: str) -> None:
        """Re-check the endpoint against SSRF at fetch time.

        Validation at account configuration alone is not enough: DNS can be
        rebound to an internal IP between set and fetch, and the setter
        permission differs from the sync permission. Residual risk (for the
        egress firewall): ``python-fints`` resolves again on connect and follows
        redirects — IP pinning of the connect is follow-up work."""
        try:
            fints_client.validate_fints_endpoint(endpoint)
        except ValueError as exc:
            raise ValidationProblem(
                "FinTS endpoint is not allowed.", code="fints_endpoint_blocked"
            ) from exc

    async def _purge_expired_sessions(self) -> None:
        """Purge expired TAN sessions globally — otherwise aborted SCA dialogs
        (encrypted) linger indefinitely; the lazy delete in :meth:`_claim_session`
        only covers the exact requested token."""
        await self.session.execute(
            delete(BankSyncSession).where(BankSyncSession.expires_at < datetime.now(UTC))
        )

    async def submit_tan(
        self, account_id: uuid.UUID, session_token: uuid.UUID, tan: str
    ) -> BankSyncResult:
        """Step 2: resume the paused dialog with the TAN (empty = decoupled poll)."""
        acc = await self._account_or_404(account_id)
        cred = await self._load_credential(account_id)
        self._guard_not_locked(cred)
        # Claim (delete) the session atomically BEFORE the network call: a second
        # parallel submit with the same token finds nothing — no replay of the
        # resumed dialog, no double audit. If the call fails, the session is gone
        # and the user restarts the sync (TAN flows are short).
        pending = await self._claim_session(session_token, account_id)
        creds = self._credentials(acc, cred)
        self._revalidate_endpoint(creds.endpoint)
        creds.tan_mechanism = pending.tan_mechanism
        # With login SCA, submit_tan fetches the transactions only after the TAN,
        # so set the fetch window (as in start_sync); harmless for a data TAN.
        creds.start_date = datetime.now(UTC).date() - timedelta(days=self.settings.fints_max_days)
        try:
            outcome = fints_client.submit_tan(creds, pending, tan)
        except (FintsBankLockedError, FintsAuthRejectedError) as exc:
            await self._record_lock(cred)
            raise ConflictError(
                "FinTS access was rejected or locked by the bank — do not retry.",
                code=self._lock_code(exc),
            ) from exc
        except FintsAccountSelectionError as exc:
            raise ValidationProblem(
                "This account could not be matched at the bank — set its IBAN.",
                code="fints_account_ambiguous",
            ) from exc
        except FintsError as exc:
            raise ServiceUnavailableError(
                "FinTS TAN submission failed.", code="fints_tan_failed"
            ) from exc
        # The network call went through (login accepted) — clear any lock cooldown.
        cred.fints_locked_until = None
        if outcome.status == "needs_tan":
            # Decoupled not yet approved: create a NEW token (the old one is
            # consumed, not reusable) and request again.
            new_token = uuid.uuid4()
            await self._store_session(acc.id, outcome, token=new_token)
            await self.session.commit()
            return self._needs_tan_result(acc.id, new_token, outcome)
        return await self._handle_outcome(acc, cred, outcome)

    async def _handle_outcome(
        self, acc: Account, cred: AccountFintsCredential, outcome: FintsOutcome
    ) -> BankSyncResult:
        """``done``: save state + stage transactions; ``needs_tan``: create a session.

        SCA state/TAN method/last sync belong to the BOOKKEEPER (credential), not
        the account."""
        # The network call went through (login accepted) — clear any lock cooldown.
        cred.fints_locked_until = None
        if outcome.status == "needs_tan":
            token = uuid.uuid4()
            await self._store_session(acc.id, outcome, token=token)
            await self.session.commit()
            return self._needs_tan_result(acc.id, token, outcome)

        if outcome.new_state is not None:
            # Store the client state (system_id/dialog state, SCA window)
            # encrypted — like the PIN, never in plaintext.
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
        """Encode the needs_tan state as an encrypted JSON blob (bytes base64-encoded)."""
        payload = {
            "client_data": base64.b64encode(outcome.client_data or b"").decode("ascii"),
            "dialog_data": base64.b64encode(outcome.dialog_data or b"").decode("ascii"),
            "tan_data": base64.b64encode(outcome.tan_data or b"").decode("ascii"),
            "tan_mechanism": outcome.tan_mechanism,
            "challenge": outcome.challenge,
            "challenge_html": outcome.challenge_html,
            "decoupled": outcome.decoupled,
            "tan_for_login": outcome.tan_for_login,
            "account_scope": list(outcome.account_scope),
        }
        return encrypt_secret(json.dumps(payload), key=self._require_enabled())

    async def _store_session(
        self, account_id: uuid.UUID, outcome: FintsOutcome, *, token: uuid.UUID
    ) -> None:
        # Tokens are always fresh (initial ``needs_tan`` and decoupled re-poll each
        # create a new UUID) — pure insert, no update path needed.
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
        """Take the TAN session atomically: ``DELETE … RETURNING`` plus immediate
        commit so a parallel submit cannot load it again (anti-replay). Scoped to
        the starting bookkeeper — another principal cannot submit a foreign TAN
        session. Expired/undecryptable yields 422 (restart the sync), not 500."""
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
        # Make the claim visible immediately — a simultaneous second submit finds nothing.
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
            account_scope=tuple(data.get("account_scope") or ()),
        )
