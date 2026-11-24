---
id: "002864"
title: The applicant reads the Bezeichnung and the status only
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation: null
scope:
  - backend/app/modules/orders
  - backend/app/modules/applications
---

# The applicant reads the Bezeichnung and the status only

An applicant session must read of each Bestellung of its Antrag only the number, the
Bezeichnung, the kind, the status and the two dates. The server must leave out every other field
for an applicant session. An applicant session must not write a Bestellung.

Reason: The applicant wants to know if the things are ordered and delivered. Prices, notes and
the shop account are internal.

Test: A backend integration test reads the Bestellungen with an applicant session and checks the
keys of the answer.
