---
id: "000141"
title: A fiscal year in use is not deleted
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/budget/tree/fiscal_years.py
scope:
  - backend/app/modules/budget
  - frontend/src/app/pages/budget
---

# A fiscal year in use is not deleted

A delete of a fiscal year with bookings or allocations must answer 409.
