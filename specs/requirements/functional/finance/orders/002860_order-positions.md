---
id: "002860"
title: A Bestellung can name positions of the Kostenaufstellung
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation: null
scope:
  - backend/app/modules/budget
  - backend/app/modules/forms
---

# A Bestellung can name positions of the Kostenaufstellung

A Bestellung can name positions of the Kostenaufstellung of its Antrag by their `id`. The server
must answer 422 `order_position_unknown` for an id that the current version of the Antrag does
not hold. A position must belong to at most one Bestellung that is not "Storniert". The server
must answer 409 `order_position_taken` for a position that a different such Bestellung names. A
position that a later version of the Antrag removes must show in the Bestellung as "Position
entfernt".

Reason: A position is the plan and the Bestellung is the purchase. With at most one Bestellung
per position the Antrag shows which positions are still open. A cancelled Bestellung bought
nothing, so its positions are open again.

Test: A backend unit test accepts the id of a position of the Antrag, refuses an unknown id and
refuses a position of a different Bestellung until that one is cancelled.
