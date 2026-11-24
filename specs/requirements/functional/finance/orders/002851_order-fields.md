---
id: "002851"
title: A Bestellung holds these fields
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
implementation:
  - backend/app/modules/orders/models.py
  - backend/app/modules/orders/schemas.py
scope:
  - backend/app/modules/orders
---

# A Bestellung holds these fields

A Bestellung must hold these fields:

| Field | Content | Required |
| --- | --- | --- |
| `title` | The Bezeichnung: what the person bought, at most 200 characters | yes |
| `kind` | `order` or `outlay` (002852) | yes |
| `status` | The status (002853) | yes |
| `supplier` | The Händler, at most 200 characters | no |
| `url` | The link to the shop or the article (002856) | no |
| `orderNumber` | The Bestellnummer of the Händler, at most 100 characters | no |
| `positionIds` | The positions of the Kostenaufstellung that the purchase covers (002860) | no |
| `plannedAmount` | The planned price in euro | no |
| `actualAmount` | The real gross price in euro | no |
| `orderedOn`, `deliveredOn` | The dates of the order and of the delivery | no |
| `buyerId`, `buyerName` | The person who bought: an account or a name | no |
| `note` | A free text, at most 2000 characters | no |
| `invoiceId` | The invoice of the purchase (002873) | no |

Each amount must be a number from 0 with at most two decimal places.

Reason: One fixed set of fields keeps the form, the API and the export the same. The amounts
follow the amounts of a booking, which are euro with cents.

Test: A backend unit test of the schema accepts a Bestellung with only the required fields and
refuses a title of 201 characters and an amount with three decimal places.
