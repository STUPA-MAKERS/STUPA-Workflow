---
id: "003036"
title: Each status has the kind open, done or void
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-26
implementation:
  - backend/app/modules/statuses/rules.py
  - backend/app/modules/orders/rules.py
scope:
  - backend/app/modules/statuses
  - backend/app/modules/orders
  - frontend/src/app/pages/admin
---

# Each status has the kind open, done or void

Each status must have one of these kinds: `open` (`Offen`: the work goes on), `done`
(`Erledigt`: the work is done) and `void` (`Verworfen`: the element did not happen). The UI must
call it `Art`, not phase. The code must read only the kind of a status and must not name a
status key. A Bestellung in a `void` status must not count to the sum of its Antrag (002868) and
must free its positions (002860). A change of a booked Bestellung to a `void` status must ask
first (002881).

Reason: The platform needs to know what a status means for the sums, the positions and the
filters of the lists. A kind says this, and the admin names and adds the statuses freely.

Test: A backend unit test adds a second `void` status to the list of the Bestellungen, sets a
Bestellung to it and reads the sum without it and its positions free.
