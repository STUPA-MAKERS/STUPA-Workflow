---
id: "000141"
title: A fiscal year in use is not deleted
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/budget
  - frontend/src/app/pages/budget
---

# A fiscal year in use is not deleted

A fiscal year with bookings or allocations answers 409 to a delete.
