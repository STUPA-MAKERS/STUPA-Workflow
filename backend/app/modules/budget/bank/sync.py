"""FinTS sync orchestration: start the fetch, resume with a TAN, manage sessions.

The module loads the PIN encrypted and decrypts it in memory only. It keeps the
paused TAN dialog encrypted and short-lived in ``bank_sync_session``.

`SyncOps` inherits the staging path from `.staging.StagingOps`. A successful
sync stages the transactions directly.
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
    """FinTS live fetch, including SCA and TAN session handling."""

    def _credentials(
        self, acc: Account, cred: AccountFintsCredential
    ) -> fints_client.FintsCredentials:
        """Merge the bank connection with the personal login data.

        The bank connection comes from the account. The login data comes from
        the credential. The method decrypts the PIN in memory only.

        Raises:
            ValidationProblem: The account has no FinTS connection, or the
                stored PIN does not decrypt.
        """
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
        """Decrypt the persisted FinTS client state to bytes.

        A state that does not decrypt (key rotation or corruption) counts as
        "no state". The next sync then forces a fresh SCA.

        Returns:
            The decrypted state, or ``None`` when there is none.
        """
        if not stored:
            return None
        try:
            return decrypt_secret(stored, key=key).encode("latin-1")
        except SecretCryptoError:
            return None

    def _guard_not_locked(self, cred: AccountFintsCredential) -> None:
        """Reject the sync while a lock cooldown runs.

        After a bank lock or a signature rejection, EVERY further login counts
        against the failed-attempt counter of the bank and can escalate the
        lock. The server-side cooldown is the authoritative brake. The frontend
        only disables the button as well.

        Raises:
            ConflictError: The cooldown has not elapsed yet.
        """
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
        """Set and persist the lock cooldown.

        `_guard_not_locked` rejects every follow-up attempt until the cooldown
        elapses.
        """
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
            # Bank locked or rejected: set the cooldown and report a 409 (do NOT
            # retry) instead of a generic 503 that invites another click.
            await self._record_lock(cred)
            raise ConflictError(
                "FinTS access was rejected or locked by the bank — do not retry.",
                code=self._lock_code(exc),
            ) from exc
        except FintsAccountSelectionError as exc:
            # Ambiguous account: the login has several and none matched the
            # configured IBAN. This is a config problem, not a bank error. Report
            # a 422 with a clear code so the treasurer sets the IBAN. NEVER run a
            # silently wrong fetch.
            raise ValidationProblem(
                "This account could not be matched at the bank — set its IBAN.",
                code="fints_account_ambiguous",
            ) from exc
        except FintsError as exc:
            # Do NOT pass the library or bank error text to the client. It can
            # carry sensitive data. The client already logged it server-side.
            raise ServiceUnavailableError(
                "FinTS sync failed.", code="fints_sync_failed"
            ) from exc
        return await self._handle_outcome(acc, cred, outcome)

    def _revalidate_endpoint(self, endpoint: str) -> None:
        """Re-check the endpoint against SSRF at fetch time.

        Validation at account configuration alone is not enough. An attacker can
        rebind DNS to an internal IP between the set and the fetch. The setter
        permission also differs from the sync permission.

        A residual risk stays for the egress firewall. ``python-fints`` resolves
        the host again on connect and follows redirects. IP pinning of the
        connect is follow-up work.

        Raises:
            ValidationProblem: The endpoint is not allowed.
        """
        try:
            fints_client.validate_fints_endpoint(endpoint)
        except ValueError as exc:
            raise ValidationProblem(
                "FinTS endpoint is not allowed.", code="fints_endpoint_blocked"
            ) from exc

    async def _purge_expired_sessions(self) -> None:
        """Purge expired TAN sessions globally.

        Without this purge, aborted SCA dialogs stay in the table forever, even
        though they are encrypted. The lazy delete in `_claim_session` covers
        only the exact requested token.
        """
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
        # Delete the session atomically BEFORE the network call. A second
        # parallel submit with the same token then finds nothing. This blocks a
        # replay of the resumed dialog and a double audit entry. If the call
        # fails, the session is gone and the user restarts the sync. TAN flows
        # are short.
        pending = await self._claim_session(session_token, account_id)
        creds = self._credentials(acc, cred)
        self._revalidate_endpoint(creds.endpoint)
        creds.tan_mechanism = pending.tan_mechanism
        # With login SCA, submit_tan fetches the transactions only after the TAN.
        # So set the fetch window as start_sync does. It is harmless for a data
        # TAN.
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
        # The network call went through, so the bank accepted the login. Clear
        # any lock cooldown.
        cred.fints_locked_until = None
        if outcome.status == "needs_tan":
            # The decoupled approval is not through yet. Create a NEW token and
            # ask again. The old token is consumed and not reusable.
            new_token = uuid.uuid4()
            await self._store_session(acc.id, outcome, token=new_token)
            await self.session.commit()
            return self._needs_tan_result(acc.id, new_token, outcome)
        return await self._handle_outcome(acc, cred, outcome)

    async def _handle_outcome(
        self, acc: Account, cred: AccountFintsCredential, outcome: FintsOutcome
    ) -> BankSyncResult:
        """Apply the outcome of a FinTS call.

        For ``done`` the method saves the state and stages the transactions. For
        ``needs_tan`` it creates a TAN session.

        The SCA state, the TAN method and the last sync time belong to the
        BOOKKEEPER (the credential), not to the account.
        """
        # The network call went through, so the bank accepted the login. Clear
        # any lock cooldown.
        cred.fints_locked_until = None
        if outcome.status == "needs_tan":
            token = uuid.uuid4()
            await self._store_session(acc.id, outcome, token=token)
            await self.session.commit()
            return self._needs_tan_result(acc.id, token, outcome)

        if outcome.new_state is not None:
            # Store the client state (system_id, dialog state, SCA window)
            # encrypted. Like the PIN, it is never in plaintext.
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

    # TAN sessions
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
        # Tokens are always fresh. The initial ``needs_tan`` and the decoupled
        # re-poll each create a new UUID. A pure insert is therefore enough and
        # no update path is necessary.
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
        """Take the TAN session atomically.

        The method runs ``DELETE … RETURNING`` and commits at once. A parallel
        submit can then no longer load the session. This blocks a replay.

        The delete is scoped to the bookkeeper that started the sync. Another
        principal cannot submit a foreign TAN session.

        Raises:
            NotFoundError: No session matches the token, the account and the
                principal.
            ValidationProblem: The session expired or does not decrypt. The
                caller gets a 422 and restarts the sync, not a 500.
        """
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
        # Make the claim visible at once. A simultaneous second submit finds nothing.
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
