---
id: "000258"
title: A booking can have sub-bookings
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/budget/tree/subbookings.py
scope:
  - backend/app/modules/budget
---

# A booking can have sub-bookings

A booking can have sub-bookings. The amount of the parent must be the sum of its sub-bookings.
