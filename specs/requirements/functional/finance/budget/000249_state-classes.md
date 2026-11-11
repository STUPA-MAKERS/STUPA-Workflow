---
id: "000249"
title: Flow states classify the amount of an Antrag
kind: functional
status: replaced
owner: frederikbeimgraben
updated: 2026-11-10
replaced_by: F/applications/flow/000572
scope:
  - backend/app/modules/budget
  - backend/app/modules/flow
---

# Flow states classify the amount of an Antrag

A cost centre lists flow states as accepted (bound) or denied (excluded). An Antrag in any
other state counts as requested. 000572 holds the rule for the state flags, and 000629 holds
the rule for bookings.
