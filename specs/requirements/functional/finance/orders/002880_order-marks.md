---
id: "002880"
title: A Bestellung shows marks for its invoice and its bookings
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
implementation:
  - backend/app/modules/orders/service.py
  - frontend/src/app/pages/applications/orders/orders.util.ts
scope:
  - backend/app/modules/orders
  - backend/app/modules/budget
  - frontend/src/app/pages/applications
---

# A Bestellung shows marks for its invoice and its bookings

A Bestellung must show the mark "Rechnung offen" or "Rechnung bezahlt" from the status of its
invoice. It must show the mark "Verbucht" with the booked amount when it has a booking. The API
must give these values as `invoiceStatus` and `bookedAmount`. The platform must read them from
the invoice and the bookings at each read and must not store them at the Bestellung.

Reason: A stored copy goes wrong when a person reverts a booking or sets an invoice to open. A
value that is read each time cannot contradict its source.

Test: A backend integration test books for a Bestellung, reads `bookedAmount`, reverts the
booking and reads 0.
