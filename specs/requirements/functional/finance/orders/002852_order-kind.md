---
id: "002852"
title: A Bestellung is an order or an Auslage
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation: null
scope:
  - backend/app/modules/budget
---

# A Bestellung is an order or an Auslage

The kind of a Bestellung must be `order` ("Bestellung") or `outlay` ("Auslage"). An Auslage is a
purchase that a person paid and that the Studierendenschaft pays back. An Auslage must name its
buyer, as an account or as a name. The kind must not change after the create.

Reason: An order and an Auslage hold the same data: what, the price, the invoice and the
booking. A second element for the Auslage would copy all of it.

Test: A backend unit test refuses an Auslage without a buyer and refuses a change of the kind.
