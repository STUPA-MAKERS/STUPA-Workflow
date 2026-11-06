---
id: "000444"
title: An Event can belong to a series
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/todos
  - frontend/src/app/features/todos
---

# An Event can belong to a series

A series (`Reihe`) belongs to one board and has a name. An Event can belong to at most one
series of its board. The Event must show the other Events of its series with their dates and
totals, the newest first.

Reason: A recurring Event, for example a party in each semester, must find the data of the
previous editions.

Test: A backend unit test lists the previous editions of an Event.
