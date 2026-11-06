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

A series (`Reihe`) has a name that is unique in the platform. A series must not belong to a
board or a Gremium. An Event can belong to at most one series. Each person who can write an
Event can create a series or select one. The Event must show the other Events of its series
that the viewer can read, with their dates and totals, the newest first. The Event must show
the number of other Events that the viewer cannot read.

Reason: A recurring Event, for example a party in each semester, must find the data of the
previous editions, also when a different board or Gremium plans the next edition.

Test: A backend unit test lists the previous editions of an Event.
