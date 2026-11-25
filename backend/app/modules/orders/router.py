"""Routes of the Bestellungen (F/finance/orders/002872).

- ``GET /applications/{id}/orders`` lists the Bestellungen of an Antrag for everybody who
  reads the Antrag. An applicant and an observer get the short view
  (F/finance/orders/002864).
- ``POST /applications/{id}/orders``, ``PATCH /orders/{id}``, ``POST /orders/{id}/status``
  and ``DELETE /orders/{id}`` need ``order.manage`` and the read of the Bestellung.
- ``POST /orders`` creates a Bestellung without an Antrag and needs ``order.manage``
  (F/finance/orders/003014). The persons with ``order.manage`` read such a Bestellung,
  because no Antrag gives a read rule.
- A person with ``budget.view``, ``budget.structure`` or ``budget.book`` reads every
  Bestellung, because these permissions read the bookings and the invoices that name it
  (F/finance/orders/002863).
- ``GET /orders/{id}/attachments`` lists the files of a Bestellung for a member who reads
  its Antrag. ``POST /orders/{id}/attachments`` and
  ``DELETE /orders/{id}/attachments/{attachment_id}`` need ``order.manage``
  (F/finance/orders/002871). The download is ``GET /attachments/{id}/download``.
- ``GET /orders/{id}/bookings`` lists the bookings that name a Bestellung, for a member who
  reads its Antrag and holds a budget read permission (F/finance/orders/002889).
- A Bestellung of an Antrag that the caller does not read answers 404
  (F/finance/orders/002863), so the answer does not tell that the Bestellung exists.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Request, Response, UploadFile, status

from app.deps import (
    DbSession,
    SettingsDep,
    get_current_applicant,
    get_current_principal,
    require_any_permission,
    require_principal,
)
from app.modules.applications.access import Access, require_app_view, resolve_app_read
from app.modules.auth.principal import Applicant, Principal
from app.modules.budget.access import BUDGET_READ_PERMISSIONS, has_budget_read
from app.modules.files.body import read_capped
from app.modules.files.queue import scan_queue_from_pool
from app.modules.files.schemas import AttachmentOut
from app.modules.files.service import FilesService, attachment_out
from app.modules.orders.access import reads_all, reads_free
from app.modules.orders.models import PurchaseOrder
from app.modules.orders.numbers import format_number
from app.modules.orders.rules import orders_sum, over_by
from app.modules.orders.schemas import (
    InvoiceOrderOut,
    InvoiceOrdersOut,
    OrderApplicantOut,
    OrderBookingOut,
    OrderCreate,
    OrderInvoiceIn,
    OrderOut,
    OrdersOut,
    OrderStatusIn,
    OrderUpdate,
)
from app.modules.orders.service import MANAGE_PERMISSION, Marks, OrderService
from app.shared.antiabuse import enforce_attachment_body_cap, rate_limit_attachments
from app.shared.errors import ForbiddenError, NotFoundError

router = APIRouter(tags=["orders"])

_ERRORS: dict[int | str, dict[str, object]] = {
    code: {"description": "problem+json"} for code in (401, 403, 404, 409, 422)
}

_UPLOAD_ERRORS: dict[int | str, dict[str, object]] = {
    **_ERRORS,
    **{code: {"description": "problem+json"} for code in (413, 415, 429, 503)},
}

ManagerDep = Annotated[Principal, Depends(require_principal(MANAGE_PERMISSION))]


def get_order_service(db: DbSession, settings: SettingsDep) -> OrderService:
    """Build the service with the current day in the local time zone."""
    return OrderService(db, today=datetime.now(ZoneInfo(settings.local_timezone)).date())


ServiceDep = Annotated[OrderService, Depends(get_order_service)]


def get_order_files(db: DbSession, request: Request, settings: SettingsDep) -> FilesService:
    """Wire the files service with the optional storage and scan queue of the app state."""
    return FilesService(
        db,
        storage=getattr(request.app.state, "object_storage", None),
        queue=scan_queue_from_pool(getattr(request.app.state, "arq_pool", None)),
        settings=settings,
    )


FilesDep = Annotated[FilesService, Depends(get_order_files)]


def order_out(
    row: PurchaseOrder,
    positions: tuple[str, ...],
    buyers: dict[UUID, str],
    marks: Marks,
    application_title: str | None,
) -> OrderOut:
    """Build the member view of a Bestellung."""
    return OrderOut(
        id=row.id,
        number=format_number(row.number),
        applicationId=row.application_id,
        applicationTitle=application_title,
        invoiceId=row.invoice_id,
        invoiceNumber=marks.invoice_number,
        invoiceStatus=marks.invoice_status,  # pyright: ignore[reportArgumentType]
        bookedAmount=marks.booked,
        title=row.title,
        kind=row.kind,  # pyright: ignore[reportArgumentType]
        status=row.status,  # pyright: ignore[reportArgumentType]
        supplier=row.supplier,
        url=row.url,
        orderNumber=row.order_number,
        positionIds=positions,
        plannedAmount=row.planned_amount,
        actualAmount=row.actual_amount,
        orderedOn=row.ordered_on,
        deliveredOn=row.delivered_on,
        buyerId=row.buyer_id,
        buyerName=row.buyer_name,
        buyerLabel=buyers.get(row.buyer_id) if row.buyer_id else row.buyer_name,
        note=row.note,
        version=row.version,
        createdAt=row.created_at,
        updatedAt=row.updated_at,
    )


def _applicant_out(row: PurchaseOrder) -> OrderApplicantOut:
    """Build the applicant view of a Bestellung: no price, no link and no note."""
    return OrderApplicantOut(
        id=row.id,
        number=format_number(row.number),
        title=row.title,
        kind=row.kind,  # pyright: ignore[reportArgumentType]
        status=row.status,  # pyright: ignore[reportArgumentType]
        orderedOn=row.ordered_on,
        deliveredOn=row.delivered_on,
    )


async def _view(service: OrderService, row: PurchaseOrder) -> OrderOut:
    """Build the member view of one Bestellung with its positions."""
    return order_out(
        row,
        (await service.positions_of([row.id]))[row.id],
        await service.buyer_names([row]),
        (await service.marks([row]))[row.id],
        (await service.application_titles([row.application_id])).get(row.application_id),
    )


async def _reads(db: DbSession, application_id: UUID | None, principal: Principal) -> bool:
    """Tell whether the caller reads the Bestellungen of the Antrag as a member.

    A read permission of the Haushalt reads every Bestellung. Without an Antrag the
    permissions of the page "Bestellungen" decide.
    """
    if reads_all(principal):
        return True
    if application_id is None:
        return reads_free(principal)
    try:
        access = await resolve_app_read(db, application_id, principal, None)
    except (ForbiddenError, NotFoundError):
        return False
    return not access.is_applicant_view


async def _readable(
    db: DbSession,
    service: OrderService,
    order_id: UUID,
    principal: Principal | None,
    applicant: Applicant | None,
    *,
    observers: bool,
) -> tuple[PurchaseOrder, bool]:
    """Return the Bestellung and whether the caller gets the short view of an applicant.

    A Bestellung without an Antrag has no applicant, so its readers always get the
    member view. A caller with a read permission of the Haushalt reads every Bestellung
    in the member view.

    Raises:
        NotFoundError: No Bestellung has this id, or the caller does not read it.
        UnauthorizedError: The request carries no identity.
    """
    row = await service.get(order_id)
    if reads_all(principal):
        return row, False
    if row.application_id is None:
        if not reads_free(principal):
            raise NotFoundError("Bestellung not found.")
        return row, False
    try:
        access = await resolve_app_read(
            db, row.application_id, principal, applicant, observers=observers
        )
    except ForbiddenError as exc:
        raise NotFoundError("Bestellung not found.") from exc
    return row, access.is_applicant_view


@router.get(
    "/applications/{application_id}/orders",
    response_model=OrdersOut,
    responses=_ERRORS,
)
async def list_orders(
    service: ServiceDep, access: Annotated[Access, Depends(require_app_view)]
) -> OrdersOut:
    """List the Bestellungen of an Antrag, the oldest first, with their sum."""
    rows = await service.list_for(access.application_id)
    if access.is_applicant_view:
        return OrdersOut(items=tuple(_applicant_out(row) for row in rows))
    positions = await service.positions_of([row.id for row in rows])
    buyers = await service.buyer_names(rows)
    marks = await service.marks(rows)
    title = (await service.application_titles([access.application_id])).get(access.application_id)
    total = orders_sum((row.status, row.actual_amount, row.planned_amount) for row in rows)
    approved = await service.approved_amount(access.application_id)
    manages = access.principal is not None and access.principal.has(MANAGE_PERMISSION)
    return OrdersOut(
        items=tuple(
            order_out(row, positions[row.id], buyers, marks[row.id], title) for row in rows
        ),
        total=total,
        approvedAmount=approved,
        overBy=over_by(total, approved),
        canManage=manages,
        canCreate=manages and await service.creatable(access.application_id),
    )


@router.post(
    "/applications/{application_id}/orders",
    response_model=OrderOut,
    status_code=status.HTTP_201_CREATED,
    responses=_ERRORS,
)
async def create_order(
    application_id: UUID,
    payload: OrderCreate,
    db: DbSession,
    service: ServiceDep,
    principal: ManagerDep,
) -> OrderOut:
    """Create a Bestellung for an approved Antrag of a type with money.

    409 ``application_not_approved``, 422 ``application_type_without_budget``, 422
    ``order_url_invalid``, 422 ``order_buyer_required``, 422 ``order_position_unknown``
    and 409 ``order_position_taken`` refuse the create.
    """
    await resolve_app_read(db, application_id, principal, None)
    row = await service.create(application_id, payload, actor=principal.sub)
    out = await _view(service, row)
    await db.commit()
    return out


@router.post(
    "/orders",
    response_model=OrderOut,
    status_code=status.HTTP_201_CREATED,
    responses=_ERRORS,
)
async def create_free_order(
    payload: OrderCreate, db: DbSession, service: ServiceDep, principal: ManagerDep
) -> OrderOut:
    """Create a Bestellung without an Antrag (F/finance/orders/003014).

    422 ``positions_need_application`` refuses positions, because the positions are
    those of the Kostenaufstellung of an Antrag.
    """
    row = await service.create(None, payload, actor=principal.sub)
    out = await _view(service, row)
    await db.commit()
    return out


@router.get(
    "/orders/{order_id}",
    response_model=OrderOut | OrderApplicantOut,
    responses=_ERRORS,
)
async def get_order(
    order_id: UUID,
    db: DbSession,
    service: ServiceDep,
    principal: Annotated[Principal | None, Depends(get_current_principal)],
    applicant: Annotated[Applicant | None, Depends(get_current_applicant)],
) -> OrderOut | OrderApplicantOut:
    """Return one Bestellung; an applicant and an observer get the short view."""
    row, short = await _readable(db, service, order_id, principal, applicant, observers=True)
    return _applicant_out(row) if short else await _view(service, row)


@router.patch("/orders/{order_id}", response_model=OrderOut, responses=_ERRORS)
async def patch_order(
    order_id: UUID,
    payload: OrderUpdate,
    db: DbSession,
    service: ServiceDep,
    principal: ManagerDep,
) -> OrderOut:
    """Change the fields that the body names; 409 ``order_version_conflict`` on an old version."""
    await _readable(db, service, order_id, principal, None, observers=False)
    row = await service.update(order_id, payload, actor=principal.sub)
    out = await _view(service, row)
    await db.commit()
    return out


@router.post("/orders/{order_id}/status", response_model=OrderOut, responses=_ERRORS)
async def post_order_status(
    order_id: UUID,
    payload: OrderStatusIn,
    db: DbSession,
    service: ServiceDep,
    principal: ManagerDep,
) -> OrderOut:
    """Set the status; "Bestellt" and "Geliefert" set their empty date to the current day."""
    await _readable(db, service, order_id, principal, None, observers=False)
    row = await service.set_status(order_id, payload.status, payload.version, actor=principal.sub)
    out = await _view(service, row)
    await db.commit()
    return out


@router.put("/orders/{order_id}/invoice", response_model=OrderOut, responses=_ERRORS)
async def put_order_invoice(
    order_id: UUID,
    payload: OrderInvoiceIn,
    db: DbSession,
    service: ServiceDep,
    principal: ManagerDep,
) -> OrderOut:
    """Set or remove the invoice of a Bestellung (F/finance/orders/002873).

    The caller needs ``order.manage`` and the read of the invoices. The gross amount of
    the invoice fills an empty real price when no other Bestellung names the invoice.
    """
    await _readable(db, service, order_id, principal, None, observers=False)
    if not has_budget_read(principal):
        raise ForbiddenError("The invoices are not readable.")
    row = await service.set_invoice(
        order_id, payload.invoice_id, payload.version, actor=principal.sub
    )
    out = await _view(service, row)
    await db.commit()
    return out


@router.get(
    "/invoices/{invoice_id}/orders",
    response_model=InvoiceOrdersOut,
    responses=_ERRORS,
)
async def list_invoice_orders(
    invoice_id: UUID,
    db: DbSession,
    service: ServiceDep,
    principal: Annotated[Principal, Depends(require_any_permission(*BUDGET_READ_PERMISSIONS))],
) -> InvoiceOrdersOut:
    """List the Bestellungen that name an invoice (F/finance/orders/002877).

    The caller reads the invoice with a read permission of the Haushalt, and this
    permission reads every Bestellung (F/finance/orders/002863), so each row has its
    values. The sum tells how much of the gross amount the Bestellungen cover.
    """
    rows = await service.of_invoice(invoice_id)
    titles = await service.application_titles([row.application_id for row in rows])
    return InvoiceOrdersOut(
        items=tuple(
            InvoiceOrderOut(
                id=row.id,
                number=format_number(row.number),
                title=row.title,
                applicationId=row.application_id,
                applicationTitle=titles.get(row.application_id),
                actualAmount=row.actual_amount,
            )
            for row in rows
        ),
        total=sum((row.actual_amount or Decimal(0) for row in rows), Decimal(0)),
    )


@router.get(
    "/orders/{order_id}/bookings",
    response_model=list[OrderBookingOut],
    responses=_ERRORS,
)
async def list_order_bookings(
    order_id: UUID,
    db: DbSession,
    service: ServiceDep,
    principal: Annotated[Principal, Depends(require_any_permission(*BUDGET_READ_PERMISSIONS))],
) -> list[OrderBookingOut]:
    """List the bookings that name a Bestellung, for the list "Verknüpft".

    The caller needs a budget read permission, like the list of the bookings. This
    permission reads the Bestellung too (F/finance/orders/002863).
    """
    await service.get(order_id)
    return [
        OrderBookingOut(id=row.id, description=row.description, amount=row.amount)
        for row in await service.bookings(order_id)
    ]


@router.delete("/orders/{order_id}", status_code=status.HTTP_204_NO_CONTENT, responses=_ERRORS)
async def delete_order(
    order_id: UUID, db: DbSession, service: ServiceDep, files: FilesDep, principal: ManagerDep
) -> Response:
    """Delete a Bestellung with its files; 409 ``order_has_bookings`` when a booking names it."""
    await _readable(db, service, order_id, principal, None, observers=False)
    await service.ensure_deletable(order_id)
    storage_keys = await files.drop_for_order(order_id, actor=principal.sub)
    await service.delete(order_id, actor=principal.sub)
    await db.commit()
    await files.remove_objects(storage_keys)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/orders/{order_id}/attachments",
    response_model=list[AttachmentOut],
    responses=_ERRORS,
)
async def list_order_attachments(
    order_id: UUID,
    db: DbSession,
    service: ServiceDep,
    files: FilesDep,
    principal: Annotated[Principal, Depends(require_principal())],
) -> list[AttachmentOut]:
    """List the files of a Bestellung, the oldest first, for a member who reads its Antrag."""
    _, short = await _readable(db, service, order_id, principal, None, observers=True)
    if short:
        raise NotFoundError("Bestellung not found.")
    return await files.list_for_order(order_id)


@router.post(
    "/orders/{order_id}/attachments",
    response_model=AttachmentOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(enforce_attachment_body_cap), Depends(rate_limit_attachments)],
    responses={
        **_ERRORS,
        **{code: {"description": "problem+json"} for code in (413, 415, 429, 503)},
    },
)
async def upload_order_attachment(
    order_id: UUID,
    db: DbSession,
    service: ServiceDep,
    files: FilesDep,
    principal: ManagerDep,
    file: Annotated[UploadFile, File()],
) -> AttachmentOut:
    """Upload a file of a Bestellung; it stays at ``scanned=false`` until the scan is clean."""
    await _readable(db, service, order_id, principal, None, observers=False)
    data = await read_capped(file, files.max_bytes)
    attachment = await files.upload_for_order(
        order_id, filename=file.filename, data=data, by=principal.sub
    )
    out = attachment_out(attachment)
    await db.commit()
    await files.enqueue_scan(out.id, actor=principal.sub)
    return out


@router.delete(
    "/orders/{order_id}/attachments/{attachment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_ERRORS,
)
async def delete_order_attachment(
    order_id: UUID,
    attachment_id: UUID,
    db: DbSession,
    service: ServiceDep,
    files: FilesDep,
    principal: ManagerDep,
) -> Response:
    """Delete one file of a Bestellung."""
    await _readable(db, service, order_id, principal, None, observers=False)
    storage_keys = await files.drop_for_order(
        order_id, actor=principal.sub, attachment_id=attachment_id
    )
    await db.commit()
    await files.remove_objects(storage_keys)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
