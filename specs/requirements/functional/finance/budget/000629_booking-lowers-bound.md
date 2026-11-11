---
id: "000629"
title: A booking lowers the bound amount of its Antrag
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
implementation:
  - backend/app/modules/budget/tree/view.py
  - backend/app/modules/budget/tree/applications.py
scope:
  - backend/app/modules/budget
---

# A booking lowers the bound amount of its Antrag

A booking for an Antrag must lower the bound amount of that Antrag by the booked amount. The
bound amount must not go below 0.

Reason: The money of a booking is expended. If it stayed bound too, the cost centre would
count it two times.
