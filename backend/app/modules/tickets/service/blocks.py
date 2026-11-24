"""Sender blocks: match a report, block and unblock a sender, list and delete blocks."""

from __future__ import annotations

import uuid

from sqlalchemy import ColumnElement, delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import Principal as PrincipalRow
from app.modules.auth.principal import Principal
from app.modules.tickets.access import AreaScope
from app.modules.tickets.models import Ticket, TicketSenderBlock
from app.modules.tickets.schemas import TicketBlockedSender, TicketDetail
from app.modules.tickets.service.common import (
    SENDER_IS_SELF,
    SENDER_UNKNOWN,
    BlockTarget,
    SwallowedReport,
    _now,
    logger,
    normalize_email,
    principal_id_of,
)
from app.modules.tickets.service.reads import ReadOps
from app.modules.tickets.service.rows import _blocked_sender
from app.shared.errors import ConflictError, NotFoundError, ValidationProblem


async def erase_sender_blocks(
    session: AsyncSession, *, principal_id: uuid.UUID | None = None, email: str | None = None
) -> None:
    """Delete the blocks of an account and of an address, without a commit (erasure)."""
    conds = (
        *((TicketSenderBlock.principal_id == principal_id,) if principal_id is not None else ()),
        *((TicketSenderBlock.email == normalize_email(email),) if email else ()),
    )
    if conds:
        await session.execute(delete(TicketSenderBlock).where(or_(*conds)))


async def sender_blocks_of(
    session: AsyncSession, *, principal_id: uuid.UUID | None, email: str
) -> list[TicketSenderBlock]:
    """Return the blocks of an account and of an address, oldest first (Auskunft)."""
    conds = (
        TicketSenderBlock.email == normalize_email(email),
        *((TicketSenderBlock.principal_id == principal_id,) if principal_id is not None else ()),
    )
    return list(
        (
            await session.scalars(
                select(TicketSenderBlock)
                .where(or_(*conds))
                .order_by(TicketSenderBlock.created_at, TicketSenderBlock.id)
            )
        ).all()
    )


class BlockOps(ReadOps):
    """The sender block ("Absender sperren") and its match on a new report."""

    async def matching_block(
        self, *, reporter_id: uuid.UUID | None, email: str | None
    ) -> uuid.UUID | None:
        """Return the block that a new report meets, else None.

        With an account the block names the account, or the account e-mail. Without
        one the block names the given e-mail, or an account with that e-mail. Both
        compares are case-insensitive.
        """
        cond = self._sender_condition(reporter_id=reporter_id, email=email)
        if cond is None:
            return None
        return await self.session.scalar(
            select(TicketSenderBlock.id).where(cond).order_by(TicketSenderBlock.created_at).limit(1)
        )

    @classmethod
    def _sender_condition(
        cls, *, reporter_id: uuid.UUID | None, email: str | None
    ) -> ColumnElement[bool] | None:
        """Return the condition of the blocks that hold back this sender, else None.

        The report, the ``senderBlocked`` flag and the unblock of a ticket share this
        condition, so a block that swallows a report always shows on the ticket and
        lifts there.
        """
        match reporter_id, email:
            case (account, _) if account is not None:
                return cls._account_condition(account)
            case (None, address) if address:
                return cls._email_condition(normalize_email(address))
            case _:
                return None

    async def _swallow(self, block_id: uuid.UUID) -> SwallowedReport:
        """Draw a number for a blocked report and count the hit; store no ticket.

        The log line names the block, never the address.
        """
        number = await self.free_number()
        await self.session.execute(
            update(TicketSenderBlock)
            .where(TicketSenderBlock.id == block_id)
            .values(hit_count=TicketSenderBlock.hit_count + 1, last_hit_at=_now())
        )
        await self.session.commit()
        logger.info("report held back by sender block %s", block_id)
        return SwallowedReport(number=number)

    async def count_block_hit(self, block_id: uuid.UUID) -> None:
        """Count one held-back mail on a sender block, without a commit."""
        await self.session.execute(
            update(TicketSenderBlock)
            .where(TicketSenderBlock.id == block_id)
            .values(hit_count=TicketSenderBlock.hit_count + 1, last_hit_at=_now())
        )
        logger.info("mail held back by sender block %s", block_id)

    def _sender_target(self, ticket: Ticket) -> BlockTarget:
        target = self.block_target(ticket)
        if target is None:
            raise ConflictError("The ticket has no sender any more.", code=SENDER_UNKNOWN)
        return target

    async def block_sender(
        self, ticket_id: uuid.UUID, principal: Principal, *, areas: AreaScope = None
    ) -> TicketDetail:
        """Block the sender of a ticket; a second block changes nothing.

        Raises:
            NotFoundError: No ticket has this id (HTTP 404).
            ConflictError: The ticket is anonymized (HTTP 409, ``ticket_sender_unknown``).
            ValidationProblem: The sender is the caller (HTTP 422, ``sender_is_self``).
        """
        ticket = await self._get(ticket_id, areas=areas)
        target = self._sender_target(ticket)
        me = await principal_id_of(self.session, principal.sub)
        if await self._is_self(target, me):
            raise ValidationProblem(
                "You cannot block yourself.",
                code=SENDER_IS_SELF,
                errors=[{"field": "ticketId", "msg": "the sender is the caller"}],
            )
        values: dict[str, object] = {
            "source_ticket_id": ticket.id,
            "created_by": me,
            "principal_id": target[1] if target[0] == "principal" else None,
            "email": target[1] if target[0] == "email" else None,
        }
        await self.session.execute(
            insert(TicketSenderBlock).values(**values).on_conflict_do_nothing()
        )
        await self.session.commit()
        return await self.detail(ticket.id, principal, areas=areas)

    async def _is_self(self, target: BlockTarget, me: uuid.UUID | None) -> bool:
        """Tell if a block target is the caller: the own account or the own address."""
        match target:
            case ("principal", account):
                return me is not None and account == me
            case ("email", address):
                own = (
                    await self.session.scalar(
                        select(PrincipalRow.email).where(PrincipalRow.id == me)
                    )
                    if me is not None
                    else None
                )
                return own is not None and normalize_email(own) == address

    async def unblock_sender(
        self, ticket_id: uuid.UUID, principal: Principal, *, areas: AreaScope = None
    ) -> TicketDetail:
        """Lift every block that holds back a ticket's sender; without one nothing changes.

        That is the block of the account and of its e-mail, or the block of the e-mail
        and of every account with that e-mail, the same blocks that swallow a report.

        Raises:
            NotFoundError: No ticket has this id (HTTP 404).
            ConflictError: The ticket is anonymized (HTTP 409, ``ticket_sender_unknown``).
        """
        ticket = await self._get(ticket_id, areas=areas)
        target = self._sender_target(ticket)
        await self.session.execute(delete(TicketSenderBlock).where(self._target_condition(target)))
        await self.session.commit()
        return await self.detail(ticket.id, principal, areas=areas)

    async def blocked_senders(self) -> list[TicketBlockedSender]:
        """List the blocked senders, newest first."""
        rows = list(
            (
                await self.session.scalars(
                    select(TicketSenderBlock).order_by(
                        TicketSenderBlock.created_at.desc(), TicketSenderBlock.id
                    )
                )
            ).all()
        )
        accounts = await self._load_accounts(
            {pid for row in rows for pid in (row.principal_id, row.created_by)}
        )
        sources = {r.source_ticket_id for r in rows if r.source_ticket_id is not None}
        numbers: dict[uuid.UUID, str] = (
            dict(
                (
                    await self.session.execute(
                        select(Ticket.id, Ticket.number).where(Ticket.id.in_(sources))
                    )
                )
                .tuples()
                .all()
            )
            if sources
            else {}
        )
        return [_blocked_sender(row, accounts, numbers) for row in rows]

    async def delete_block(self, block_id: uuid.UUID) -> None:
        """Lift one block by its id.

        Raises:
            NotFoundError: No block has this id (HTTP 404).
        """
        removed = (
            await self.session.execute(
                delete(TicketSenderBlock)
                .where(TicketSenderBlock.id == block_id)
                .returning(TicketSenderBlock.id)
            )
        ).first()
        if removed is None:
            raise NotFoundError(f"block {block_id} not found")
        await self.session.commit()
