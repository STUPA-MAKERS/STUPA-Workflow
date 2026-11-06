---
id: "000253"
title: Amounts are euro only
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/budget/tree_schemas.py
  - backend/app/modules/budget/decision.py
scope:
  - backend/app/modules/budget
---

# Amounts are euro only

Every amount must be in EUR. A booking, a transfer and a sub-booking must have an amount
greater than 0 and at most 9 999 999 999.99. A larger amount must answer 422, never 500. A 0 €
approval must write no booking.
