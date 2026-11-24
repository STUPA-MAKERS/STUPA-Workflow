---
id: "002875"
title: A row shows the difference between the real and the planned price
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation: null
scope:
  - frontend/src/app/pages/applications
---

# A row shows the difference between the real and the planned price

When a Bestellung has a real price and a planned price that differ, its row and its detail must
show the difference in euro with its sign.

Reason: The planned price is what the Gremium saw. The person who books must see at once that a
purchase cost more or less.

Test: A frontend unit test renders a Bestellung with 100,00 € planned and 112,50 € real and
reads "+12,50 €".
