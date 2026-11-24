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
not hold. Two Bestellungen can name the same position. A position that a later version of the
Antrag removes must show in the Bestellung as "Position entfernt".

Reason: A position is the plan and the Bestellung is the purchase. The reference shows which
plan a purchase fulfils. One position can need two purchases, and one purchase can cover two
positions.

Test: A backend unit test accepts the id of a position of the Antrag and refuses an unknown id.
