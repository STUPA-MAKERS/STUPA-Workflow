---
id: "003088"
title: The platform keeps only sums of pretix orders
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-25
implementation: null
scope:
  - backend/app/
  - frontend/src/app/
---
# The platform keeps only sums of pretix orders

The platform must read from pretix only the numbers and sums of 003084 and the data of the
events of the organizer. It must not store, log or show the name, the email address, the
address or a different personal value of an order, an attendee or a payment.

Reason: The orders hold personal data of the guests. The planning of an Event needs only the
numbers, and data that the platform does not hold needs no erasure and no export (002532).

Test: A backend unit test reads a fake order with a name and an email address and finds neither
value in the stored sales.
