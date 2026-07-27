"""Shared base of the ``service.BankService`` mixins.

The class holds the constructor and the helpers that several sub-areas use. These
helpers cover the feature and principal gates, the account and credential lookup,
the audit hook and the balance carry-over. They also build the output projection
of a staged statement line.
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

# Cap on the lines per import or fetch (anti-DoS). A 10-MiB MT940 can carry tens
# of thousands of transactions, and each staged line costs 1 to 2 queries.
MAX_STATEMENT_LINES = 10_000


class BankServiceBase:
    """Base of the FinTS-/file-based account reconciliation (bound to a session)."""

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
        # The system separates personal FinTS credentials and TAN sessions per
        # bookkeeper. The sync and credential path therefore needs the principal
        # id. The file import has no bank access and works without it.
        self.principal_id = principal_id

    def _require_enabled(self) -> str:
        """Return the FinTS encryption key or 503 (feature off)."""
        key = self.settings.fints_enc_key
        if not key:
            raise ServiceUnavailableError("FinTS is not configured (no encryption key set).")
        return key

    def _require_principal(self) -> uuid.UUID:
        """Return the principal id of the bookkeeper, or raise a 503.

        The router always supplies the id for an authenticated FinTS call. A
        missing id breaks an internal invariant.
        """
        if self.principal_id is None:
            raise ServiceUnavailableError("FinTS requires an authenticated principal.")
        return self.principal_id

    async def _load_credential(self, account_id: uuid.UUID) -> AccountFintsCredential:
        """Load the personal credentials of the bookkeeper for an account.

        Raises:
            ValidationProblem: The account has no credential. The code is 422
                ``fints_no_credential``, and the frontend then prompts for the
                first connect.
        """
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
        """Store the bank balance and the as-of date on the account.

        The method overwrites the values only when the source delivered a balance
        (HKSAL, ``:62F:`` or CLBD). Otherwise it keeps the last known balance.
        """
        if balance is None:
            return
        as_of = (
            datetime.combine(balance.as_of, datetime.min.time(), tzinfo=UTC)
            if balance.as_of is not None
            else datetime.now(UTC)
        )
        # Recency guard: never overwrite a newer balance with an older file import.
        # An equal or missing as-of date (``None``) always updates the balance.
        if (
            acc.fints_balance_at is not None
            and balance.as_of is not None
            and as_of < acc.fints_balance_at
        ):
            return
        acc.fints_last_balance = balance.amount
        acc.fints_balance_at = as_of

    @staticmethod
    def _line_out(
        line: BankStatementLine,
        suggested_path_key: str | None,
        matched_expense_id: uuid.UUID | None = None,
    ) -> StatementLineOut:
        # ALWAYS resolve counterparty and purpose from the raw data. Never use the
        # stored counterparty_* or purpose columns, because they can come from an
        # older parser version, for example a "KRZL" placeholder or a glued IBAN and
        # purpose. CAMT raw data without GVC fields falls back to the column.
        name, iban = normalize.resolve_counterparty(line.raw_payload, credit=line.amount > 0)
        if not name and not iban:
            # Fall back to the stored column (CAMT or legacy) but still drop
            # the placeholders.
            name = normalize.clean_counterparty_name(line.counterparty_name)
            iban = line.counterparty_iban
        purpose = normalize.resolve_purpose(line.raw_payload)
        if purpose is None:
            purpose = line.purpose
        # Make Sparkasse batch-booking purposes ("DATEI-NR. ...") readable for a
        # person. This affects the display only. The column and raw data stay
        # unchanged.
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
            matchedExpenseId=matched_expense_id,
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
