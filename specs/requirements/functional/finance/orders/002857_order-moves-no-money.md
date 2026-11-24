---
id: "002857"
title: A Bestellung moves no money
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
implementation: null
scope:
  - backend/app/modules/orders
  - backend/app/modules/budget
---

# A Bestellung moves no money

A Bestellung must not change the requested, the bound, the expended or the available amount of a
Kostenstelle. Only the Antrag and its bookings must set these figures. The close of a
Haushaltsjahr must not lock the Bestellungen of its Anträge. A booking from such a Bestellung
must follow the rule of the closed year (F/finance/budget/000252).

Reason: The approved amount of the Antrag is bound, and a booking lowers it
(F/finance/budget/000629). If a Bestellung counted too, the Kostenstelle would count the same
money two times. A delivery can arrive after the close of the year.

Test: A backend integration test reads the figures of a Kostenstelle before and after the create
of a Bestellung, expects no difference, closes the year and sets the Bestellung to "Geliefert".
