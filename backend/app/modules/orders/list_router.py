"""Routes of the page "Bestellungen" (F/finance/orders/002883).

- ``GET /orders`` lists the Bestellungen of the Anträge that the caller reads as a member,
  the newest change first. It needs ``order.manage`` or ``budget.view``.
- ``GET /orders/pending-applications`` lists the approved Anträge without a Bestellung
  (F/finance/orders/002934), with the same permissions.
- ``GET /orders/export.xlsx`` gives the Bestellungen of the filter as a file and needs
  ``order.manage`` (F/finance/orders/002886).

The app includes this router before the router of one Bestellung, because the path
``/orders/{order_id}`` would else take the fixed paths.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.deps import DbSession, require_any_permission
from app.modules.audit.actions import AuditAction
from app.modules.audit.service import record as audit_record
from app.modules.auth.principal import Principal
from app.modules.orders.listing import OrderFilter, OrderListing
from app.modules.orders.models import PurchaseOrder
from app.modules.orders.router import ManagerDep, ServiceDep, order_out
from app.modules.orders.rules import OrderKind, Segment
from app.modules.orders.schemas import OrderOut, PendingApplicationOut
from app.modules.orders.service import MANAGE_PERMISSION, OrderService
from app.shared.paging import Page, PageParams

router = APIRouter(tags=["orders"])

_ERRORS: dict[int | str, dict[str, object]] = {
    code: {"description": "problem+json"} for code in (401, 403, 422)
}

#: The permissions of which one opens the page (F/finance/orders/002883).
PAGE_PERMISSIONS: tuple[str, ...] = (MANAGE_PERMISSION, "budget.view")
#: The most rows of one export.
EXPORT_MAX_ROWS = 10_000

ReaderDep = Annotated[Principal, Depends(require_any_permission(*PAGE_PERMISSIONS))]

_KIND_LABEL = {"order": "Bestellung", "outlay": "Auslage"}
_STATUS_LABEL = {
    "planned": "Geplant",
    "ordered": "Bestellt",
    "delivered": "Geliefert",
    "cancelled": "Storniert",
}
_HEADERS: tuple[str, ...] = (
    "Nummer",
    "Bezeichnung",
    "Art",
    "Status",
    "Antrag",
    "Händler",
    "Bestellnummer",
    "Geplanter Preis",
    "Tatsächlicher Preis",
    "Verbucht",
    "Bestellt am",
    "Geliefert am",
    "Käufer:in",
    "Rechnung",
)
#: The places of the amount columns in `_HEADERS`.
_MONEY_COLUMNS = frozenset({7, 8, 9})


def _wanted(
    segment: Annotated[Segment | None, Query()] = None,
    fiscal_year_id: Annotated[UUID | None, Query(alias="fiscalYear")] = None,
    budget_id: Annotated[UUID | None, Query(alias="budget")] = None,
    gremium_id: Annotated[UUID | None, Query(alias="gremium")] = None,
    kind: Annotated[OrderKind | None, Query()] = None,
    buyer_id: Annotated[UUID | None, Query(alias="buyer")] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> OrderFilter:
    """Read the filter of the page from the query (F/finance/orders/002885)."""
    return OrderFilter(
        segment=segment,
        fiscal_year_id=fiscal_year_id,
        budget_id=budget_id,
        gremium_id=gremium_id,
        kind=kind,
        buyer_id=buyer_id,
        q=q,
    )


FilterDep = Annotated[OrderFilter, Depends(_wanted)]


async def _views(service: OrderService, rows: list[PurchaseOrder]) -> list[OrderOut]:
    """Build the member views of the rows with four reads for the whole page."""
    positions = await service.positions_of([row.id for row in rows])
    buyers = await service.buyer_names(rows)
    marks = await service.marks(rows)
    titles = await service.application_titles([row.application_id for row in rows])
    return [
        order_out(row, positions[row.id], buyers, marks[row.id], titles.get(row.application_id))
        for row in rows
    ]


@router.get("/orders", response_model=Page[OrderOut], responses=_ERRORS)
async def list_all_orders(
    db: DbSession,
    service: ServiceDep,
    principal: ReaderDep,
    wanted: FilterDep,
    page: Annotated[PageParams, Depends()],
) -> Page[OrderOut]:
    """List the Bestellungen of the readable Anträge, the newest change first.

    ``segment`` is ``open``, ``delivered`` or ``done`` (F/finance/orders/002884).
    ``budget`` covers the subtree of the Kostenstelle.
    """
    rows, total = await OrderListing(db).page(
        principal, wanted, limit=page.limit, offset=page.offset
    )
    return Page(
        items=await _views(service, rows), total=total, limit=page.limit, offset=page.offset
    )


@router.get(
    "/orders/pending-applications",
    response_model=Page[PendingApplicationOut],
    responses=_ERRORS,
)
async def list_pending_applications(
    db: DbSession,
    principal: ReaderDep,
    wanted: FilterDep,
    page: Annotated[PageParams, Depends()],
) -> Page[PendingApplicationOut]:
    """List the approved Anträge of a type with money that have no Bestellung."""
    return await OrderListing(db).pending(principal, wanted, limit=page.limit, offset=page.offset)


@router.get("/orders/export.xlsx", responses=_ERRORS)
async def export_orders_xlsx(
    db: DbSession, service: ServiceDep, principal: ManagerDep, wanted: FilterDep
) -> Response:
    """Export the Bestellungen of the filter as ``.xlsx`` with the amounts as numbers."""
    from app.shared.xlsx import XLSX_MEDIA_TYPE, build_table_workbook

    rows, _ = await OrderListing(db).page(principal, wanted, limit=EXPORT_MAX_ROWS, offset=0)
    data = build_table_workbook(
        title="Bestellungen",
        head=(),
        headers=_HEADERS,
        rows=[
            (
                item.number,
                item.title,
                _KIND_LABEL[item.kind],
                _STATUS_LABEL[item.status],
                item.application_title or "",
                item.supplier or "",
                item.order_number or "",
                item.planned_amount,
                item.actual_amount,
                item.booked_amount,
                item.ordered_on.isoformat() if item.ordered_on else "",
                item.delivered_on.isoformat() if item.delivered_on else "",
                item.buyer_label or "",
                item.invoice_number or "",
            )
            for item in await _views(service, rows)
        ],
        money_columns=_MONEY_COLUMNS,
    )
    await audit_record(
        db,
        actor=principal.sub,
        action=AuditAction.EXPORT,
        target_type="export",
        target_id="bestellungen.xlsx",
        data={"rows": len(rows)},
    )
    await db.commit()
    return Response(
        content=data,
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="bestellungen.xlsx"'},
    )
