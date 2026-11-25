---
id: "002863"
title: A person who reads the Haushalt or the Antrag reads the Bestellungen
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-25
implementation:
  - backend/app/modules/orders/access.py
  - backend/app/modules/orders/router.py
scope:
  - backend/app/modules/orders
  - backend/app/modules/applications
---

# A person who reads the Haushalt or the Antrag reads the Bestellungen

A person with one of the permissions `budget.view`, `budget.structure` and `budget.book` must
read every Bestellung, with and without an Antrag. These are the permissions that read the
bookings and the invoices. Every other person must read a Bestellung when the person reads its
Antrag. A Bestellung without an Antrag (003014) must also be read by a person with
`order.manage`. The server must answer 404 for a Bestellung that the person does not read. The
files, the links and the search hits of a Bestellung must follow this rule.

Reason: A booking and an invoice name their Bestellung, so the person who reads the bookings
and the invoices needs the Bestellungen too. One read right for the three makes a role easy to
plan. The Bestellungen are also a part of the story of an Antrag, so its readers keep them.
Without an Antrag no Gremium owns the purchase, so the person who orders reads it.

Test: A backend integration test reads a Bestellung of an Antrag that the person does not read
with each of the three permissions, and gets 404 without them. It reads the Bestellungen as a
member of the Gremium of the Antrag. It reads a Bestellung without an Antrag with
`order.manage` and gets 404 without the four permissions.
