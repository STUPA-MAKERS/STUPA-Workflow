"""Service of the Bestellungen: reads, create, change, status change, delete and revert.

Only the request of a person creates a Bestellung (F/finance/orders/002930): no flow action,
no cron and no migration calls `OrderService.create`.

The service functions do not commit; the router owns the transaction. Each write raises
the version, writes an audit entry with the old and the new values
(F/finance/orders/002865) and, for the create, a status change and the delete, a timeline
event of the Antrag (F/finance/orders/002866).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.application_types.models import ApplicationType
from app.modules.applications.models import Application, ApplicationOrderEvent
from app.modules.applications.position_ids import position_ids
from app.modules.applications.service.service_base import _title_of
from app.modules.audit.actions import AuditAction
from app.modules.audit.models import AuditEntry
from app.modules.audit.service import record as audit_record
from app.modules.auth.models import Principal as PrincipalRow
from app.modules.budget.tree_models import BudgetExpense, Invoice
from app.modules.flow.models import State
from app.modules.orders.models import PurchaseOrder, PurchaseOrderPosition
from app.modules.orders.numbers import format_number
from app.modules.orders.rules import buyer_missing, price_from_invoice, status_dates, url_valid
from app.modules.orders.schemas import OrderCreate, OrderUpdate
from app.modules.orders.webhook_fields import emit_order_event
from app.modules.statuses.service import StatusReader, in_phase
from app.shared.errors import ConflictError, NotFoundError, ValidationProblem

#: The permission that every write of a Bestellung needs (F/finance/orders/002862).
MANAGE_PERMISSION = "order.manage"

#: The fields that a change can set, as wire name and column name.
_FIELDS: tuple[tuple[str, str], ...] = (
    ("title", "title"),
    ("kind", "kind"),
    ("supplier", "supplier"),
    ("url", "url"),
    ("orderNumber", "order_number"),
    ("plannedAmount", "planned_amount"),
    ("actualAmount", "actual_amount"),
    ("orderedOn", "ordered_on"),
    ("deliveredOn", "delivered_on"),
    ("buyerId", "buyer_id"),
    ("buyerName", "buyer_name"),
    ("note", "note"),
)
#: The column of each wire name of an audit entry. The invoice has its own route, so it is
#: no field of a change.
_COLUMN: Mapping[str, str] = dict(_FIELDS) | {"invoiceId": "invoice_id"}
_STATUS_KEYS: tuple[str, ...] = ("status", "orderedOn", "deliveredOn")


def _wire(value: object) -> object:
    """Render a column value for the audit entry: a string, or None."""
    return None if value is None else str(value)


def _parse(key: str, raw: object) -> object:
    """Read a value of an audit entry back into the type of its column."""
    if raw is None:
        return None
    text = str(raw)
    match key:
        case "plannedAmount" | "actualAmount":
            return Decimal(text)
        case "orderedOn" | "deliveredOn":
            return date.fromisoformat(text)
        case "buyerId" | "invoiceId":
            return UUID(text)
        case _:
            return text


def _refused(code: str, field: str, msg: str) -> ValidationProblem:
    """Build the 422 of a refused field."""
    return ValidationProblem(
        "The Bestellung cannot be saved.", code=code, errors=[{"field": field, "msg": msg}]
    )


@dataclass(frozen=True, slots=True)
class Marks:
    """What a Bestellung shows of its invoice and its bookings (F/finance/orders/002880).

    Attributes:
        invoice_number: The number of the invoice, else None.
        invoice_status: ``open`` or ``paid``, else None without an invoice.
        booked: The sum of the bookings that name the Bestellung.
    """

    invoice_number: str | None = None
    invoice_status: str | None = None
    booked: Decimal = Decimal(0)


@dataclass(frozen=True, slots=True)
class OrderService:
    """The Bestellungen, bound to an ``AsyncSession``.

    Attributes:
        today: The current day in the local time zone, for the status dates.
    """

    session: AsyncSession
    today: date

    async def get(self, order_id: UUID) -> PurchaseOrder:
        """Return one Bestellung.

        Raises:
            NotFoundError: No Bestellung has this id.
        """
        row = await self.session.get(PurchaseOrder, order_id)
        if row is None:
            raise NotFoundError("Bestellung not found.")
        return row

    async def list_for(self, application_id: UUID) -> list[PurchaseOrder]:
        """Return the Bestellungen of an Antrag, the oldest first."""
        rows = await self.session.scalars(
            select(PurchaseOrder)
            .where(PurchaseOrder.application_id == application_id)
            .order_by(PurchaseOrder.created_at, PurchaseOrder.id)
        )
        return list(rows)

    async def positions_of(self, order_ids: Sequence[UUID]) -> dict[UUID, tuple[str, ...]]:
        """Return the position ids of each of the Bestellungen."""
        rows = (
            (
                await self.session.execute(
                    select(PurchaseOrderPosition.order_id, PurchaseOrderPosition.position_id)
                    .where(PurchaseOrderPosition.order_id.in_(order_ids))
                    .order_by(PurchaseOrderPosition.position_id)
                )
            ).all()
            if order_ids
            else []
        )
        return {
            order_id: tuple(pos for oid, pos in rows if oid == order_id) for order_id in order_ids
        }

    async def buyer_names(self, rows: Sequence[PurchaseOrder]) -> dict[UUID, str]:
        """Return the display name of each account that is the buyer of one of the rows."""
        ids = {row.buyer_id for row in rows if row.buyer_id is not None}
        found = (
            (
                await self.session.execute(
                    select(PrincipalRow.id, PrincipalRow.display_name).where(
                        PrincipalRow.id.in_(ids)
                    )
                )
            ).all()
            if ids
            else []
        )
        return {principal_id: name for principal_id, name in found if name}

    async def marks(self, rows: Sequence[PurchaseOrder]) -> dict[UUID, Marks]:
        """Return the marks of each of the rows.

        The function reads the invoices and the bookings at each call. The Bestellung
        stores no copy, because a copy goes wrong when a person reverts a booking or
        sets an invoice to open.
        """
        invoice_ids = {row.invoice_id for row in rows if row.invoice_id is not None}
        invoices: dict[UUID | None, tuple[str | None, str | None]] = (
            {
                invoice_id: (number, status)
                for invoice_id, number, status in (
                    await self.session.execute(
                        select(Invoice.id, Invoice.number, Invoice.status).where(
                            Invoice.id.in_(invoice_ids)
                        )
                    )
                ).all()
            }
            if invoice_ids
            else {}
        )
        booked = (
            dict(
                (
                    await self.session.execute(
                        select(BudgetExpense.order_id, func.sum(BudgetExpense.amount))
                        .where(
                            BudgetExpense.order_id.in_([row.id for row in rows]),
                            BudgetExpense.parent_expense_id.is_(None),
                        )
                        .group_by(BudgetExpense.order_id)
                    )
                )
                .tuples()
                .all()
            )
            if rows
            else {}
        )
        return {
            row.id: Marks(
                invoice_number=invoices.get(row.invoice_id, (None, None))[0],
                invoice_status=invoices.get(row.invoice_id, (None, None))[1],
                booked=Decimal(booked.get(row.id) or 0),
            )
            for row in rows
        }

    async def bookings(self, order_id: UUID) -> list[BudgetExpense]:
        """Return the bookings that name the Bestellung, the oldest first."""
        rows = await self.session.scalars(
            select(BudgetExpense)
            .where(
                BudgetExpense.order_id == order_id,
                BudgetExpense.parent_expense_id.is_(None),
            )
            .order_by(BudgetExpense.created_at, BudgetExpense.id)
        )
        return list(rows)

    async def application_titles(
        self, application_ids: Sequence[UUID | None]
    ) -> dict[UUID | None, str]:
        """Return the title of each of the Anträge that has one.

        A Bestellung without an Antrag gives None, which is no key of the answer.
        """
        ids = {application_id for application_id in application_ids if application_id is not None}
        found = (
            (
                await self.session.execute(
                    select(Application.id, Application.data).where(Application.id.in_(ids))
                )
            ).all()
            if ids
            else []
        )
        return {
            application_id: title
            for application_id, data in found
            if (title := _title_of(data)) is not None
        }

    async def of_invoice(self, invoice_id: UUID) -> list[PurchaseOrder]:
        """Return the Bestellungen that name the invoice, the oldest first.

        Raises:
            NotFoundError: No invoice has this id.
        """
        if await self.session.get(Invoice, invoice_id) is None:
            raise NotFoundError("Invoice not found.")
        rows = await self.session.scalars(
            select(PurchaseOrder)
            .where(PurchaseOrder.invoice_id == invoice_id)
            .order_by(PurchaseOrder.created_at, PurchaseOrder.id)
        )
        return list(rows)

    async def set_invoice(
        self, order_id: UUID, invoice_id: UUID | None, version: int, *, actor: str
    ) -> PurchaseOrder:
        """Set or remove the invoice of a Bestellung (F/finance/orders/002873).

        The gross amount of the invoice fills an empty real price when no other
        Bestellung names the invoice (F/finance/orders/002874).

        Raises:
            NotFoundError: No Bestellung or no invoice has the id.
            ConflictError: A different version is current.
        """
        row = await self.get(order_id)
        self._check_version(row, version)
        invoice = await self.session.get(Invoice, invoice_id) if invoice_id is not None else None
        if invoice_id is not None and invoice is None:
            raise NotFoundError("Invoice not found.")
        others = (
            await self.session.scalar(
                select(func.count())
                .select_from(PurchaseOrder)
                .where(PurchaseOrder.invoice_id == invoice_id, PurchaseOrder.id != row.id)
            )
            if invoice is not None
            else 0
        )
        actual = (
            price_from_invoice(row.actual_amount, invoice.gross_amount, others or 0)
            if invoice is not None
            else row.actual_amount
        )
        values = {
            "invoiceId": invoice_id,
            **({"actualAmount": actual} if actual != row.actual_amount else {}),
        }
        return await self._write(row, values, None, actor=actor, action=AuditAction.ORDER_UPDATE)

    async def approved_amount(self, application_id: UUID) -> Decimal | None:
        """Return the approved amount of the Antrag."""
        return await self.session.scalar(
            select(Application.approved_amount).where(Application.id == application_id)
        )

    async def _gate(self, application_id: UUID) -> tuple[bool, bool]:
        """Return whether the type of the Antrag has money and whether its state is approved.

        The function reads only the flag of the state and never the key of a state,
        because the flow is the configuration of each installation.
        """
        row = (
            await self.session.execute(
                select(ApplicationType.has_budget, State.is_approved)
                .select_from(Application)
                .join(ApplicationType, ApplicationType.id == Application.type_id)
                .outerjoin(State, State.id == Application.current_state_id)
                .where(Application.id == application_id)
            )
        ).first()
        return (bool(row[0]), bool(row[1])) if row is not None else (False, False)

    async def creatable(self, application_id: UUID) -> bool:
        """Tell whether the Antrag takes a new Bestellung (F/finance/orders/002858)."""
        has_budget, approved = await self._gate(application_id)
        return has_budget and approved

    async def _check_buyer(self, kind: str, buyer_id: UUID | None, name: str | None) -> None:
        """Check the buyer of a Bestellung.

        Raises:
            ValidationProblem: An Auslage has no buyer (``order_buyer_required``), or
                no account has the id (``order_buyer_unknown``).
        """
        if buyer_missing(kind, buyer_id, name):
            raise _refused("order_buyer_required", "buyerId", "An Auslage needs its buyer.")
        if buyer_id is not None and await self.session.get(PrincipalRow, buyer_id) is None:
            raise _refused("order_buyer_unknown", "buyerId", "No account has this id.")

    async def _check_positions(
        self, application_id: UUID | None, wanted: Sequence[str], *, own: UUID | None
    ) -> None:
        """Check the positions of a Bestellung (F/finance/orders/002860).

        Raises:
            ValidationProblem: The Bestellung has no Antrag, so it has no
                Kostenaufstellung (``positions_need_application``,
                F/finance/orders/003014), or the current version of the Antrag holds
                no position with an id (``order_position_unknown``).
            ConflictError: A different Bestellung that is not cancelled names a
                position (``order_position_taken``).
        """
        if not wanted:
            return
        if application_id is None:
            raise _refused(
                "positions_need_application",
                "positionIds",
                "A Bestellung without an Antrag has no positions.",
            )
        data = await self.session.scalar(
            select(Application.data).where(Application.id == application_id)
        )
        known = position_ids(data or {})
        if any(pos not in known for pos in wanted):
            raise _refused(
                "order_position_unknown", "positionIds", "The Antrag has no such position."
            )
        taken = await self.session.scalar(
            select(PurchaseOrderPosition.position_id)
            .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderPosition.order_id)
            .where(
                PurchaseOrder.application_id == application_id,
                ~in_phase(PurchaseOrder.status, "order", "void"),
                PurchaseOrder.id != own,
                PurchaseOrderPosition.position_id.in_(wanted),
            )
            .limit(1)
        )
        if taken is not None:
            raise ConflictError(
                "A different Bestellung names this position.", code="order_position_taken"
            )

    async def _set_positions(self, order_id: UUID, wanted: Sequence[str]) -> None:
        """Replace the positions of a Bestellung."""
        await self.session.execute(
            delete(PurchaseOrderPosition).where(PurchaseOrderPosition.order_id == order_id)
        )
        self.session.add_all(
            PurchaseOrderPosition(order_id=order_id, position_id=pos)
            for pos in dict.fromkeys(wanted)
        )
        await self.session.flush()

    async def _event(self, row: PurchaseOrder, actor: str, kind: str, **extra: str) -> None:
        """Write one timeline event of the Antrag and emit the webhook event of it.

        The create and a status change are webhook events (F/finance/orders/002891). A
        Bestellung without an Antrag has no timeline to write to.
        """
        if row.application_id is not None:
            self.session.add(
                ApplicationOrderEvent(
                    application_id=row.application_id,
                    order_id=row.id,
                    actor=actor,
                    kind=kind,
                    payload={"number": format_number(row.number), "title": row.title, **extra},
                )
            )
        match kind:
            case "created":
                await emit_order_event(self.session, row)
            case "status":
                await emit_order_event(self.session, row, previous=extra["from"])
            case _:
                pass

    async def create(
        self, application_id: UUID | None, payload: OrderCreate, *, actor: str
    ) -> PurchaseOrder:
        """Create a Bestellung for an Antrag, or without one (F/finance/orders/003014).

        Only a Bestellung of an Antrag needs the approved Antrag of a type with money.

        Raises:
            ValidationProblem: The type of the Antrag has no money
                (``application_type_without_budget``), the link is no http or https
                address (``order_url_invalid``), or the buyer or a position is refused.
            ConflictError: The Antrag is in no approved state
                (``application_not_approved``), or a position is taken.
        """
        has_budget, approved = (
            await self._gate(application_id) if application_id is not None else (True, True)
        )
        if not has_budget:
            raise ValidationProblem(
                "The type of the Antrag has no money.", code="application_type_without_budget"
            )
        if not approved:
            raise ConflictError("The Antrag is not approved.", code="application_not_approved")
        if payload.url is not None and not url_valid(payload.url):
            raise _refused("order_url_invalid", "url", "The link must be an http or https address.")
        await self._check_buyer(payload.kind, payload.buyer_id, payload.buyer_name)
        await self._check_positions(application_id, payload.position_ids, own=None)
        statuses = StatusReader(self.session)
        status = await statuses.require(
            "order", payload.status or await statuses.start_key("order")
        )
        ordered_on, delivered_on = status_dates(
            status.sets_date, payload.ordered_on, payload.delivered_on, self.today
        )
        row = PurchaseOrder(
            application_id=application_id,
            kind=payload.kind,
            status=status.key,
            title=payload.title,
            supplier=payload.supplier or None,
            url=payload.url or None,
            order_number=payload.order_number or None,
            planned_amount=payload.planned_amount,
            actual_amount=payload.actual_amount,
            ordered_on=ordered_on,
            delivered_on=delivered_on,
            buyer_id=payload.buyer_id,
            buyer_name=payload.buyer_name or None,
            note=payload.note or None,
            version=1,
            created_by=actor,
        )
        self.session.add(row)
        await self.session.flush()
        await self._set_positions(row.id, payload.position_ids)
        await self._event(row, actor, "created")
        await audit_record(
            self.session,
            actor=actor,
            action=AuditAction.ORDER_CREATE,
            target_type="order",
            target_id=str(row.id),
            data={
                "applicationId": _wire(application_id),
                "number": format_number(row.number),
                "after": {
                    "status": row.status,
                    **{key: _wire(getattr(row, col)) for key, col in _FIELDS},
                },
            },
        )
        return row

    @staticmethod
    def _check_version(row: PurchaseOrder, version: int) -> None:
        """Refuse a write that read an older version (F/finance/orders/002867).

        Raises:
            ConflictError: A different version is current (``order_version_conflict``).
        """
        if row.version != version:
            raise ConflictError(
                "A different person changed the Bestellung.", code="order_version_conflict"
            )

    async def _write(
        self,
        row: PurchaseOrder,
        values: Mapping[str, object],
        positions: Sequence[str] | None,
        *,
        actor: str,
        action: AuditAction,
        extra: Mapping[str, Any] | None = None,
    ) -> PurchaseOrder:
        """Set the wire values on the row, raise the version and write the audit entry."""
        old_positions = (await self.positions_of([row.id]))[row.id]
        before = {key: _wire(getattr(row, _COLUMN.get(key, key))) for key in values}
        for key, value in values.items():
            setattr(row, _COLUMN.get(key, key), value)
        if positions is not None:
            await self._set_positions(row.id, positions)
        row.version = row.version + 1
        await self.session.flush()
        after = {key: _wire(value) for key, value in values.items()}
        changed = {key for key in values if before[key] != after[key]}
        moved = positions is not None and tuple(sorted(set(positions))) != old_positions
        await audit_record(
            self.session,
            actor=actor,
            action=action,
            target_type="order",
            target_id=str(row.id),
            data={
                "applicationId": _wire(row.application_id),
                "number": format_number(row.number),
                "before": {
                    **{key: before[key] for key in values if key in changed},
                    **({"positionIds": list(old_positions)} if moved else {}),
                },
                "after": {
                    **{key: after[key] for key in values if key in changed},
                    **({"positionIds": sorted(set(positions or ()))} if moved else {}),
                },
                **(extra or {}),
            },
        )
        await self.session.refresh(row)
        return row

    async def update(self, order_id: UUID, payload: OrderUpdate, *, actor: str) -> PurchaseOrder:
        """Change the fields that the body names.

        Raises:
            NotFoundError: No Bestellung has this id.
            ConflictError: A different version is current, or a position is taken.
            ValidationProblem: The link, the buyer or a position is refused.
        """
        row = await self.get(order_id)
        self._check_version(row, payload.version)
        sent = payload.model_dump(by_alias=True, exclude_unset=True)
        values = {key: sent[key] for key, _ in _FIELDS if key in sent}
        if values.get("title") is None and "title" in values:
            raise _refused("order_title_required", "title", "A Bestellung needs its Bezeichnung.")
        if values.get("kind") is None and "kind" in values:
            raise _refused("order_kind_required", "kind", "A Bestellung needs its kind.")
        url = values.get("url")
        if isinstance(url, str) and url and not url_valid(url):
            raise _refused("order_url_invalid", "url", "The link must be an http or https address.")
        merged = {col: getattr(row, col) for _, col in _FIELDS} | {
            _COLUMN[key]: value for key, value in values.items()
        }
        await self._check_buyer(merged["kind"], merged["buyer_id"], merged["buyer_name"])
        positions = payload.position_ids if "positionIds" in sent else None
        if positions is not None:
            await self._check_positions(row.application_id, positions, own=row.id)
        cleaned = {key: (value if value != "" else None) for key, value in values.items()}
        return await self._write(
            row, cleaned, positions, actor=actor, action=AuditAction.ORDER_UPDATE
        )

    async def set_status(
        self, order_id: UUID, status: str, version: int, *, actor: str
    ) -> PurchaseOrder:
        """Set the status and the dates that follow from it (F/finance/orders/002853).

        A person sets each status from each other status of the list. A Bestellung that
        leaves the phase ``void`` takes its positions again, so the check of the
        positions runs (F/administration/admin/003036).

        Raises:
            NotFoundError: No Bestellung has this id.
            ValidationProblem: The status is not in the list (``status_unknown``).
            ConflictError: A different version is current, or a position is taken.
        """
        row = await self.get(order_id)
        self._check_version(row, version)
        previous = row.status
        statuses = StatusReader(self.session)
        target = await statuses.require("order", status)
        was = await statuses.get("order", previous)
        if (was is None or was.phase == "void") and target.phase != "void":
            own = (await self.positions_of([row.id]))[row.id]
            await self._check_positions(row.application_id, own, own=row.id)
        ordered_on, delivered_on = status_dates(
            target.sets_date, row.ordered_on, row.delivered_on, self.today
        )
        values = {"status": status, "orderedOn": ordered_on, "deliveredOn": delivered_on}
        result = await self._write(row, values, None, actor=actor, action=AuditAction.ORDER_STATUS)
        if previous != status:
            await self._event(row, actor, "status", **{"from": previous, "to": status})
        return result

    async def ensure_deletable(self, order_id: UUID) -> None:
        """Refuse the delete of a Bestellung with a booking.

        The router asks before it drops the files, so a refused delete keeps them.

        Raises:
            ConflictError: A booking names the Bestellung (``order_has_bookings``).
        """
        booked = await self.session.scalar(
            select(BudgetExpense.id).where(BudgetExpense.order_id == order_id).limit(1)
        )
        if booked is not None:
            raise ConflictError("A booking names the Bestellung.", code="order_has_bookings")

    async def delete(self, order_id: UUID, *, actor: str) -> None:
        """Delete a Bestellung with its positions.

        A Bestellung with a booking is a record of the finances, so a person cancels it
        and does not delete it (F/finance/orders/002878).

        Raises:
            NotFoundError: No Bestellung has this id.
            ConflictError: A booking names the Bestellung (``order_has_bookings``).
        """
        row = await self.get(order_id)
        await self.ensure_deletable(order_id)
        positions = (await self.positions_of([row.id]))[row.id]
        await self._event(row, actor, "deleted")
        await audit_record(
            self.session,
            actor=actor,
            action=AuditAction.ORDER_DELETE,
            target_type="order",
            target_id=str(row.id),
            data={
                "applicationId": _wire(row.application_id),
                "number": format_number(row.number),
                "before": {
                    "status": row.status,
                    **{key: _wire(getattr(row, col)) for key, col in _FIELDS},
                    "positionIds": list(positions),
                },
            },
        )
        await self.session.delete(row)
        await self.session.flush()

    async def revert_audit(self, entry: AuditEntry, actor: str) -> PurchaseOrder:
        """Take back a change or a status change (F/finance/orders/002865).

        The revert sets the old values of the entry. It refuses when the Bestellung is
        gone or when a later write changed one of these fields again, because the old
        value would then delete that later change.

        Raises:
            ConflictError: The entry holds no old values (``not_revertable``), the
                Bestellung is gone (``order_gone``), or a later write changed a field
                (``stale_revert``).
        """
        data = entry.data or {}
        before: Mapping[str, Any] = data.get("before") or {}
        after: Mapping[str, Any] = data.get("after") or {}
        if not before or not entry.target_id:
            raise ConflictError("This audit entry is not revertable.", code="not_revertable")
        row = await self.session.get(PurchaseOrder, UUID(entry.target_id))
        if row is None:
            raise ConflictError("The Bestellung is gone.", code="order_gone")
        fields = {key: value for key, value in before.items() if key != "positionIds"}
        current_positions = list((await self.positions_of([row.id]))[row.id])
        stale = any(
            _wire(getattr(row, _COLUMN.get(key, key))) != after.get(key) for key in fields
        ) or ("positionIds" in before and current_positions != after.get("positionIds"))
        if stale:
            raise ConflictError("A later change touched the same fields.", code="stale_revert")
        old_invoice = fields.get("invoiceId")
        if old_invoice is not None and await self.session.get(Invoice, UUID(old_invoice)) is None:
            raise ConflictError("The old invoice is gone.", code="not_revertable")
        positions = (
            tuple(str(pos) for pos in before["positionIds"]) if "positionIds" in before else None
        )
        if positions:
            await self._check_positions(row.application_id, positions, own=row.id)
        previous = row.status
        result = await self._write(
            row,
            {key: _parse(key, value) for key, value in fields.items()},
            positions,
            actor=actor,
            action=(AuditAction.ORDER_STATUS if "status" in fields else AuditAction.ORDER_UPDATE),
            extra={"revertedAuditId": entry.id},
        )
        if "status" in fields and previous != row.status:
            await self._event(row, actor, "status", **{"from": previous, "to": row.status})
        return result
