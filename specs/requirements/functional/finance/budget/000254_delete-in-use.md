---
id: "000254"
title: A cost centre in use is not deleted
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/budget/tree/nodes.py
scope:
  - backend/app/modules/budget
---

# A cost centre in use is not deleted

The delete of a cost centre with children, bookings or assigned Anträge must answer 409. The
allocations of the cost centre must go with it.
