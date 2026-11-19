---
id: "001703"
title: The bulk result shows success or error per Antrag
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
implementation: null
scope:
  - backend/app/modules/applications
  - frontend/src/app/pages/applications
---

# The bulk result shows success or error per Antrag

A bulk action (001701, 001702) must run each Antrag in its own transaction. An error at one
Antrag must not stop the others. The result must list each Antrag with `Erledigt` (`Done`) or the
error text.

Reason: An all-or-nothing action fails the whole round for one changed Antrag.

Test: A backend integration test runs a bulk action with one failing Antrag and checks the result list.
