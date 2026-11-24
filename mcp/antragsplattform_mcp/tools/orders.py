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

from mcp.server.fastmcp import FastMCP

from .. import schemas as S
from ..schemas import dump_create, dump_patch
from ._common import ToolGroup, api
from .meetings import _attachment_part

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
async def order_create(application_id: str, order: S.OrderCreate) -> dict:
    """Create a Bestellung for an Antrag. Requires `order.manage`.

    409 `application_not_approved` when the Antrag is not approved, 422
    `application_type_without_budget` for a type without money, 422 `order_url_invalid`,
    422 `order_buyer_required` (status `ordered` or `delivered` needs `buyerId` or
    `buyerName`), 422 `order_buyer_unknown`, 422 `order_position_unknown` and 409
    `order_position_taken` (the position belongs to another Bestellung). Audited.
    """
    return await api().post(f"/applications/{application_id}/orders", json=dump_create(order))


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
    `accessible`, `id`, `number`, `title`, `applicationId`, `applicationTitle` and
    `actualAmount`. An item of an Antrag that the caller does not read has
    `accessible` false and no other value.
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


def register(mcp: FastMCP) -> None:
    """Register the order tools on the shared FastMCP instance."""
    group.register(mcp)
