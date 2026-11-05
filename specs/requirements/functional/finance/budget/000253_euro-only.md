---
id: "000253"
title: Amounts are euro only
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/budget
---

# Amounts are euro only

Every amount is in EUR. An amount must be greater than 0 and at most 9 999 999 999.99. A
larger amount answers 422, never 500.
