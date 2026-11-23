---
id: "002701"
title: The Bereich Plattform takes the reports of the help menu
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-23
implementation: null
scope:
  - backend/app/modules/tickets
  - frontend/src/app/pages/tickets
---

# The Bereich Plattform takes the reports of the help menu

The platform must have the built-in Bereich `Plattform`. A report from the help menu without a
chosen Bereich must become a ticket of `Plattform`. An admin must not be able to delete
`Plattform`.

Reason: The reports on the platform itself need a place that exists on every installation
(000150).

Test: A unit test sends a report from the help menu and expects the ticket in `Plattform`. A
second test deletes `Plattform` and expects 409.
