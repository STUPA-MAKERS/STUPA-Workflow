---
id: "002857"
title: A Bestellung changes no figure of the Haushalt
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation: null
scope:
  - backend/app/modules/budget
---

# A Bestellung changes no figure of the Haushalt

A Bestellung must not change the requested, the bound, the expended or the available amount of a
Kostenstelle. Only the Antrag and its bookings must set these figures.

Reason: The approved amount of the Antrag is bound, and a booking lowers it
(F/finance/budget/000629). If a Bestellung counted too, the Kostenstelle would count the same
money two times.

Test: A backend integration test reads the figures of a Kostenstelle before and after the create
of a Bestellung and expects no difference.
