---
id: "003014"
title: A Bestellung can have no Antrag
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-25
implementation:
  - backend/app/modules/orders/service.py
  - frontend/src/app/pages/orders/order-form.component.ts
scope:
  - backend/app/modules/orders
  - frontend/src/app/pages
---

# A Bestellung can have no Antrag

A person with `order.manage` must be able to create a Bestellung without an Antrag. The form of
a new Bestellung must offer the choice "Ohne Antrag" beside the Anträge, and it must not set it
by itself. A Bestellung without an Antrag has no positions of a Kostenaufstellung, no approved
amount, no sum with a warning (002868) and no comments (002935), and the platform offers no
transition after its status change (002931). The server must answer 422
`positions_need_application` when such a Bestellung names a position. Each other rule of a
Bestellung holds for it: the kinds, the statuses, the files, the invoice, the bookings, the
audit entries, the search, the link kind and the export.

Reason: A booking from the time before the platform has no Antrag. The person records its
purchase as a Bestellung so that the booking can name it (002878). The way with an Antrag stays
the usual one, because only an Antrag gives the approved amount to compare with.

Test: A backend integration test creates a Bestellung without an Antrag, refuses a position for
it, changes its status and books for it. A frontend unit test saves the form with "Ohne Antrag"
and finds no positions and no sum.
