"""Bank accounts and their FinTS connection config."""

from __future__ import annotations

import uuid
from uuid import UUID

from sqlalchemy import and_, select, update

from app.modules.audit.actions import AuditAction
from app.modules.budget.bank.client import validate_fints_endpoint
from app.modules.budget.tree.service_base import BudgetTreeServiceBase
from app.modules.budget.tree_models import Account, AccountFintsCredential
from app.modules.budget.tree_schemas import (
    AccountCreate,
    AccountOption,
    AccountOut,
    AccountUpdate,
)
from app.shared.errors import NotFoundError, ValidationProblem


class AccountOps(BudgetTreeServiceBase):
    """CRUD for bank accounts, including the FinTS bank connection."""

    @staticmethod
    def _account_out(a: Account) -> AccountOut:
        return AccountOut(
            id=a.id,
            name=a.name,
            iban=a.iban,
            active=a.active,
            fintsEndpoint=a.fints_endpoint,
            fintsBlz=a.fints_blz,
            # An account is FinTS-capable with an endpoint and a BLZ. A personal
            # login or PIN belongs to a principal, not to the account master data.
            fintsConfigured=bool(a.fints_endpoint and a.fints_blz),
            fintsLastBalance=a.fints_last_balance,
            fintsBalanceAt=a.fints_balance_at,
        )

    def _apply_fints_config(self, acc: Account, payload: AccountCreate | AccountUpdate) -> bool:
        """Apply the FinTS bank connection (endpoint and BLZ) from the payload.

        Returns:
            True when the connection changed. The caller then discards the
            persisted dialog state of every booker. The account now points at a
            different bank and needs a fresh SCA.

        Raises:
            ValidationProblem: The endpoint fails the SSRF check.
        """
        fields = payload.model_fields_set
        changed = False
        for col in ("fints_endpoint", "fints_blz"):
            if col in fields:
                value = getattr(payload, col) or None
                if col == "fints_endpoint" and value:
                    # SSRF guard: no internal/non-https endpoint.
                    try:
                        validate_fints_endpoint(value)
                    except ValueError as exc:
                        raise ValidationProblem(
                            str(exc), code="fints_endpoint_invalid"
                        ) from exc
                setattr(acc, col, value)
                changed = True
        return changed

    async def _reset_fints_states(self, account_id: UUID) -> None:
        """Discard the persisted SCA state of ALL bookers of this account.

        A changed bank connection invalidates every ``system_id`` and dialog
        state. The next sync of each booker then forces a fresh SCA.
        """
        await self.session.execute(
            update(AccountFintsCredential)
            .where(AccountFintsCredential.account_id == account_id)
            .values(fints_state=None)
        )

    async def list_accounts(self) -> list[AccountOut]:
        rows = (await self.session.scalars(select(Account).order_by(Account.name))).all()
        return [self._account_out(a) for a in rows]

    async def list_account_options(self) -> list[AccountOption]:
        """List active accounts as id and name (no IBAN) for booking dropdowns.

        ``fintsHasCredential`` and ``fintsLastSyncAt`` resolve PER requesting
        booker. An account can be FinTS-capable while this user has stored no own
        credentials yet.
        """
        from app.modules.auth.models import Principal as PrincipalRow

        pid = select(PrincipalRow.id).where(PrincipalRow.sub == self.actor).scalar_subquery()
        rows = (
            await self.session.execute(
                select(
                    Account,
                    AccountFintsCredential.fints_pin_encrypted.isnot(None),
                    AccountFintsCredential.fints_last_sync_at,
                )
                .outerjoin(
                    AccountFintsCredential,
                    and_(
                        AccountFintsCredential.account_id == Account.id,
                        AccountFintsCredential.principal_id == pid,
                    ),
                )
                .where(Account.active.is_(True))
                .order_by(Account.name)
            )
        ).all()
        return [
            AccountOption(
                id=a.id,
                name=a.name,
                fintsConfigured=bool(a.fints_endpoint and a.fints_blz),
                fintsHasCredential=bool(has_cred),
                fintsLastSyncAt=last_sync,
                fintsLastBalance=a.fints_last_balance,
                fintsBalanceAt=a.fints_balance_at,
            )
            for a, has_cred, last_sync in rows
        ]

    async def _audit_fints_config(self, acc: Account) -> None:
        """Audit the FinTS config change WITHOUT any PIN or plaintext secret."""
        await self._audit(
            AuditAction.BANK_ACCOUNT_CONFIG,
            target_type="account",
            target_id=str(acc.id),
            data={"endpoint": acc.fints_endpoint, "blz": acc.fints_blz},
        )

    async def create_account(self, payload: AccountCreate) -> AccountOut:
        acc = Account(id=uuid.uuid4(), name=payload.name, iban=payload.iban, active=payload.active)
        fints_changed = self._apply_fints_config(acc, payload)
        self.session.add(acc)
        if fints_changed:
            await self._audit_fints_config(acc)
        await self.session.commit()
        return self._account_out(acc)

    async def update_account(self, account_id: UUID, payload: AccountUpdate) -> AccountOut:
        acc = await self.session.get(Account, account_id)
        if acc is None:
            raise NotFoundError(f"account {account_id} not found")
        for field in ("name", "iban", "active"):
            if field in payload.model_fields_set and getattr(payload, field) is not None:
                setattr(acc, field, getattr(payload, field))
        if self._apply_fints_config(acc, payload):
            # The bank connection changed, so discard all stored SCA states.
            await self._reset_fints_states(acc.id)
            await self._audit_fints_config(acc)
        await self.session.commit()
        return self._account_out(acc)

    async def delete_account(self, account_id: UUID) -> None:
        acc = await self.session.get(Account, account_id)
        if acc is None:
            raise NotFoundError(f"account {account_id} not found")
        await self.session.delete(acc)  # ON DELETE SET NULL: bookings keep account_id NULL
        await self.session.commit()
