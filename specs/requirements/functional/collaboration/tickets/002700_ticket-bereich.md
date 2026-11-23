---
id: "002700"
title: Each ticket belongs to one Bereich
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - backend/app/modules/tickets
  - frontend/src/app/pages/tickets
---

# Each ticket belongs to one Bereich

Each ticket must belong to exactly one Bereich. A Bereich must have a name that is unique on the
platform.

Reason: A general ticket system holds the work of more than one team. The Bereich is the unit
that separates the tickets, the rights and the settings of the teams.

Test: A unit test creates a ticket without a Bereich and expects a refusal.
