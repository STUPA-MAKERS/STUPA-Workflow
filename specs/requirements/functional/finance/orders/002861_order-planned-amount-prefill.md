---
id: "002861"
title: The form fills the planned price and the link from the preferred offers
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
implementation:
  - frontend/src/app/pages/applications/orders/orders.util.ts
  - frontend/src/app/pages/applications/orders/order-dialog.component.ts
scope:
  - frontend/src/app/pages/applications
---

# The form fills the planned price and the link from the preferred offers

When a person picks positions in the form of a Bestellung, the form must set the planned price
to the sum of the preferred offers of these positions. With exactly one position it must set the
link to the first `http://` or `https://` address in the text of the preferred offer. The form
must not change a value that the person typed.

Reason: The preferred offer is the price that the Gremium approved, and applicants write the
address of the shop into it. The prefill saves the copy by hand.

Test: A frontend unit test picks one position and reads the price and the link, then types
both, picks a second position and reads the typed values.
