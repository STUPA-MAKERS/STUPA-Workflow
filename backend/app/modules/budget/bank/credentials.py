"""Personal FinTS credentials per bookkeeper and account.

The module creates, replaces and deletes the encrypted login data. It also builds the
connection status for the frontend: is the account FinTS-capable, are own credentials
stored, and is a cooldown active?
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select

from app.modules.audit.actions import AuditAction
from app.modules.budget.bank.service_base import BankServiceBase
from app.modules.budget.tree_models import Account, AccountFintsCredential
from app.modules.budget.tree_schemas import FintsCredentialIn, FintsCredentialStatus
from app.shared.crypto import encrypt_secret
from app.shared.errors import NotFoundError, ValidationProblem


class CredentialOps(BankServiceBase):
    """Management of personal FinTS credentials."""

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
        """Return the connection status of the bookkeeper for an account.

        The status says whether the account is FinTS-capable, and whether THIS user
        stored their own credentials.
        """
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
        """Create or replace the personal credentials of the bookkeeper (login and PIN).

        The service stores the PIN encrypted. On a change it discards the previous SCA
        state and TAN mechanism, because new data forces a fresh SCA. The admin must
        have set the bank connection (endpoint and BLZ) on the account.

        Raises:
            ValidationProblem: The account has no FinTS connection configured.
        """
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
            # New credentials invalidate the previous dialog state (fresh SCA).
            cred.fints_state = None
            cred.fints_tan_mechanism = None
        # Audit WITHOUT login or PIN. The `actor` identifies the bookkeeper.
        await self._audit(AuditAction.BANK_CREDENTIAL_SET, target_id=str(account_id))
        await self.session.commit()
        return self._credential_status(acc, cred)

    async def delete_credential(self, account_id: uuid.UUID) -> None:
        """Delete the personal credentials of the bookkeeper for an account.

        Raises:
            NotFoundError: The bookkeeper has no credential for this account.
        """
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
