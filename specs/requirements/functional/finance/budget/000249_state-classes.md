---
id: "000249"
title: Flow states classify the amount of an Antrag
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/budget
  - backend/app/modules/flow
---

# Flow states classify the amount of an Antrag

A cost centre lists flow states as accepted (bound) or denied (excluded). An Antrag in any
other state counts as requested. A booking for an Antrag lowers its bound amount by the
booked amount, down to 0.
