---
id: "002881"
title: The cancel of a booked Bestellung asks first
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
implementation: null
scope:
  - frontend/src/app/pages/applications
  - backend/app/modules/orders
---

# The cancel of a booked Bestellung asks first

When a person sets a Bestellung with a booking to "Storniert", the frontend must ask with the
booked amount in the text. The cancel must keep the bookings. The platform must not create a
booking for the refund.

Reason: The money of a booking is spent. A refund is an income that a person books when it
arrives, with its own date and amount.

Test: A frontend unit test cancels a booked Bestellung and expects the dialog. A backend test
reads the bookings after the cancel.
