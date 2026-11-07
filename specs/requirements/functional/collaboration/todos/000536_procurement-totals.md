---
id: "000536"
title: A Beschaffung shows the estimate against the costs
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-07
implementation: null
scope:
  - backend/app/modules/todos
  - frontend/src/app/features/todos
  - backend/app/modules/applications
  - backend/app/modules/budget
---

# A Beschaffung shows the estimate against the costs

A Beschaffung must show the estimated amount, the approved amount of its linked Anträge, the
amount of its linked invoices and the expenses of its linked Buchungen. It must show the
difference between the estimate and the expenses. The totals must count all linked elements,
because each reader of the card can read them.

Reason: The Gremium sees whether a purchase stays inside the estimate, across Kostenstellen and fiscal years.

Test: A backend unit test computes the totals for a board reader without `budget.read`.
