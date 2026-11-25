"""Order tools: the Bestellungen of an Antrag (`/applications/{id}/orders`, `/orders`).

A Bestellung is one purchase at one supplier for an approved Antrag of a type with
money. Only a person creates one; the platform never does. The status is `planned`,
`ordered`, `delivered` or `cancelled`, and a person sets each of them by hand. A member
who reads the Antrag reads its Bestellungen; the applicant and an observer get number,
title, kind, status and the two dates only. A write needs `order.manage`.

A Bestellung has files of its own. They are not attachments of the Antrag, so
`list_attachments` does not show them. `download_attachment` and `get_attachment` serve
them to a member who reads the Antrag.
"""

from __future__ import annotations

from typing import Literal

from mcp.server.fastmcp import FastMCP

from .. import schemas as S
from ..schemas import dump_create, dump_patch
from ._common import ToolGroup, api, params
from .meetings import _attachment_part, download_to

group = ToolGroup()


@group.tool
async def order_list(application_id: str) -> dict:
    """List the Bestellungen of an Antrag that the caller reads, the oldest first.

    The answer has `items`, `total` (the sum of the prices of the Bestellungen that are
    not cancelled: the real price, else the planned one), `approvedAmount`, `overBy`
    (set when the sum is above the approved amount; this only warns), `canManage` and
    `canCreate` (the caller holds `order.manage`, and the Antrag is approved and of a
    type with money). Each item has `id`, `number` (`B-` and eight characters), `title`,
    `kind`, `status`, `supplier`, `url`, `orderNumber`, `positionIds`, `plannedAmount`,
    `actualAmount`, `orderedOn`, `deliveredOn`, `buyerId`, `buyerName`, `buyerLabel`
    (the name of the account of the buyer, else the typed name), `note`, `invoiceId`,
    `invoiceNumber`, `invoiceStatus` (`open` or `paid`, read from the invoice),
    `bookedAmount` (the sum of the bookings that name the Bestellung) and `version`.
    The applicant view has no prices, no link and no note.
    """
    return await api().get(f"/applications/{application_id}/orders")


@group.tool
async def order_get(order_id: str) -> dict:
    """Return one Bestellung (as an item of `order_list`); 404 without read of its Antrag."""
    return await api().get(f"/orders/{order_id}")


@group.tool
async def order_create(application_id: str | None, order: S.OrderCreate) -> dict:
    """Create a Bestellung for an Antrag. Requires `order.manage`.

    `application_id` null creates a Bestellung without an Antrag, for a purchase from
    the time before the platform. It takes no positions (422
    `positions_need_application`), and the checks of the Antrag do not apply.

    409 `application_not_approved` when the Antrag is not approved, 422
    `application_type_without_budget` for a type without money, 422 `order_url_invalid`,
    422 `order_buyer_required` (status `ordered` or `delivered` needs `buyerId` or
    `buyerName`), 422 `order_buyer_unknown`, 422 `order_position_unknown` and 409
    `order_position_taken` (the position belongs to another Bestellung). Audited.
    """
    path = "/orders" if application_id is None else f"/applications/{application_id}/orders"
    return await api().post(path, json=dump_create(order))


@group.tool
async def order_update(order_id: str, patch: S.OrderPatch) -> dict:
    """Change the fields of a Bestellung that `patch` sets. Requires `order.manage`.

    `patch.version` is the `version` as last read; 409 `order_version_conflict` on a
    mismatch. The errors of `order_create` apply. The status changes with
    `order_set_status`. Audited, and the audit log can take the change back.
    """
    return await api().patch(f"/orders/{order_id}", json=dump_patch(patch))


@group.tool
async def order_set_status(order_id: str, status: S.OrderStatus, version: int) -> dict:
    """Set the status of a Bestellung; any status follows any other. Requires `order.manage`.

    `ordered` sets an empty `orderedOn` to the current day and `delivered` an empty
    `deliveredOn`. Both need a buyer (422 `order_buyer_required`). 409
    `order_version_conflict` on an old `version`. The timeline of the Antrag shows the
    change. Audited.
    """
    return await api().post(
        f"/orders/{order_id}/status", json={"status": status, "version": version}
    )


@group.tool
async def order_delete(order_id: str) -> dict:
    """Delete a Bestellung with its files. Requires `order.manage`. Audited.

    409 `order_has_bookings` when a booking names the Bestellung: cancel it with
    `order_set_status` and keep it.
    """
    return await api().delete(f"/orders/{order_id}")


@group.tool
async def order_set_invoice(order_id: str, invoice_id: str | None, version: int) -> dict:
    """Set the invoice of a Bestellung, or remove it with `invoice_id` null.

    Requires `order.manage` and the read of the invoices. A Bestellung has at most one
    invoice, and one invoice can belong to many Bestellungen. The gross amount of the
    invoice fills an empty `actualAmount` when no other Bestellung names the invoice.
    409 `order_version_conflict` on an old `version`. Audited.
    """
    return await api().put(
        f"/orders/{order_id}/invoice", json={"invoiceId": invoice_id, "version": version}
    )


@group.tool
async def invoice_orders(invoice_id: str) -> dict:
    """List the Bestellungen that name an invoice. Requires the read of the invoices.

    The answer has `items` and `total` (the sum of the real prices). An item has
    `id`, `number`, `title`, `applicationId`, `applicationTitle` and `actualAmount`.
    """
    return await api().get(f"/invoices/{invoice_id}/orders")


@group.tool
async def order_attachments(order_id: str) -> dict:
    """List the files of a Bestellung, the oldest first, for a member who reads its Antrag.

    Each entry holds `id`, `filename`, `mime`, `size` and `scanned`. `scanned` stays
    false until the virus scan reports clean; only then does `download_attachment` work.
    """
    return await api().get(f"/orders/{order_id}/attachments")


@group.tool
async def order_attachment_upload(
    order_id: str, file_path: str, filename: str | None = None
) -> dict:
    """Upload a local file as a file of a Bestellung. Requires `order.manage`.

    `POST /orders/{id}/attachments` (multipart field `file`). `file_path` is a path on
    the machine of the MCP server. `filename` overrides the stored name. The types and
    the size limit are those of `upload_attachment` (415, 413, 503 without storage).

    Returns:
        The file: `id`, `filename`, `mime`, `size`, `scanned` (false: the scan still runs).
    """
    name, data, mime = _attachment_part(file_path, filename)
    return await api().post(f"/orders/{order_id}/attachments", files={"file": (name, data, mime)})


@group.tool
async def order_attachment_delete(order_id: str, attachment_id: str) -> dict:
    """Delete one file of a Bestellung. Requires `order.manage`. Audited."""
    return await api().delete(f"/orders/{order_id}/attachments/{attachment_id}")


OrderSegment = Literal["open", "delivered", "done"]


def _filter(
    fiscal_year: str | None,
    budget: str | None,
    gremium: str | None,
    kind: S.OrderKind | None,
    buyer: str | None,
    q: str | None,
) -> dict[str, object]:
    """The filter of the order list as query parameters, without the empty ones."""
    return params(
        fiscalYear=fiscal_year, budget=budget, gremium=gremium, kind=kind, buyer=buyer, q=q
    )


@group.tool
async def order_list_all(
    segment: OrderSegment | None = None,
    fiscal_year: str | None = None,
    budget: str | None = None,
    gremium: str | None = None,
    kind: S.OrderKind | None = None,
    buyer: str | None = None,
    q: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> dict:
    """List the Bestellungen that the caller reads, the newest change first.

    Requires `order.manage` or a read permission of the Haushalt, and a read permission of
    the Haushalt lists every Bestellung. `segment` is `open` (planned or ordered),
    `delivered` (delivered and not fully booked) or `done`. `fiscal_year`, `budget`
    (a Kostenstelle with its subtree), `gremium` and `buyer` are ids. `q` searches the
    number, the title, the supplier and the order number of the supplier. The answer is
    a page: `items` (as in `order_list`, with `applicationId` and `applicationTitle`),
    `total`, `limit`, `offset`.
    """
    return await api().get(
        "/orders",
        params={
            **params(segment=segment, limit=limit, offset=offset),
            **_filter(fiscal_year, budget, gremium, kind, buyer, q),
        },
    )


@group.tool
async def order_pending_applications(
    fiscal_year: str | None = None,
    budget: str | None = None,
    gremium: str | None = None,
    q: str | None = None,
    with_orders: bool = False,
    limit: int | None = None,
    offset: int | None = None,
) -> dict:
    """List the approved Anträge of a type with money that have no Bestellung.

    Requires `order.manage` or a read permission of the Haushalt. A cancelled Bestellung
    does not count.
    `with_orders` lists the Anträge that have a Bestellung too: each Antrag that can
    take a new one. Each item has `id`, `title`, `gremiumId`, `gremiumName` and
    `approvedAmount`. The platform never creates a Bestellung for them.
    """
    return await api().get(
        "/orders/pending-applications",
        params={
            **params(limit=limit, offset=offset, withOrders=True if with_orders else None),
            **_filter(fiscal_year, budget, gremium, None, None, q),
        },
    )


@group.tool
async def order_bookings(order_id: str) -> dict:
    """List the bookings that name a Bestellung: `id`, `description` and `amount`.

    Requires a read permission of the budget and the read of the Antrag.
    """
    return await api().get(f"/orders/{order_id}/bookings")


@group.tool
async def export_orders_xlsx(
    target_path: str,
    segment: OrderSegment | None = None,
    fiscal_year: str | None = None,
    budget: str | None = None,
    gremium: str | None = None,
    kind: S.OrderKind | None = None,
    buyer: str | None = None,
    q: str | None = None,
    overwrite: bool = False,
) -> dict:
    """Export the order list as `.xlsx` to a local file. Requires `finance.export`.

    The filters work as in `order_list_all`.
    """
    return await download_to(
        "GET",
        "/orders/export.xlsx",
        target_path,
        overwrite=overwrite,
        fallback="bestellungen.xlsx",
        query={**params(segment=segment), **_filter(fiscal_year, budget, gremium, kind, buyer, q)},
    )


def register(mcp: FastMCP) -> None:
    """Register the order tools on the shared FastMCP instance."""
    group.register(mcp)
