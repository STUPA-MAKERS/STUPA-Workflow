---
id: "003088"
title: The platform keeps no personal data of pretix orders
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-25
implementation:
  - backend/app/modules/pretix/client.py
scope:
  - backend/app/
  - frontend/src/app/
---
# The platform keeps no personal data of pretix orders

The platform must read from pretix only the numbers and sums of 003084, the data of the events
of the organizer, and of each order its code, sum, status and dates for the bookings of 003086.
It must not store, log or show the name, the email address, the address or a different personal
value of an order, an attendee or a payment.

Reason: The orders hold personal data of the guests. The planning and the bookings of an Event
need only the numbers and the code of an order, and data that the platform does not hold needs
no erasure and no export (002532).

Test: A backend unit test reads a fake order with a name and an email address and finds neither
value in the stored sales or in a booking.
