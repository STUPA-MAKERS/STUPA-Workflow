---
id: "002852"
title: A Bestellung is an order or an Auslage
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
implementation:
  - backend/app/modules/orders/rules.py
  - backend/app/modules/orders/service.py
scope:
  - backend/app/modules/orders
---

# A Bestellung is an order or an Auslage

The kind of a Bestellung must be `order` ("Bestellung") or `outlay` ("Auslage"). An Auslage is a
purchase that a person paid and that the organization pays back. An Auslage must name its
buyer, as an account or as a name. A person must be able to change the kind of a Bestellung. The
server must answer 422 `order_buyer_required` for a change to Auslage without a buyer.

Reason: An order and an Auslage hold the same data: what, the price, the invoice and the
booking. A second element for the Auslage would copy all of it. A wrong click at the create must
not force a delete.

Test: A backend unit test refuses an Auslage without a buyer, changes an order with a buyer to
an Auslage and refuses the change without a buyer.
