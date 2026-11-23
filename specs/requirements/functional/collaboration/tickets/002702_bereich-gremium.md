---
id: "002702"
title: A Bereich belongs to one Gremium or to no Gremium
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - backend/app/modules/tickets
  - frontend/src/app/pages/tickets
---

# A Bereich belongs to one Gremium or to no Gremium

A Bereich must name at most one Gremium as its owner. The Bereich `Plattform` must have no
Gremium.

Reason: The owner decides who works in the Bereich (002703). The tickets on the platform are the
work of the platform team and not of a Gremium.

Test: A unit test saves a Bereich with two Gremien and expects 422.
