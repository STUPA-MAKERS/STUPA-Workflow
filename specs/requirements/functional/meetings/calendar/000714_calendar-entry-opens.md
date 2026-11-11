---
id: "000714"
title: An entry opens its own element
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
implementation: null
scope:
  - frontend/src/app/features
---

# An entry opens its own element

A meeting entry must open the meeting, a card entry must open the card, and a Termin must open
the Termin sheet. An entry of an external calendar must open a read-only sheet with the title,
the time, the place, the description and the name of the calendar.

Reason: The Kalender does not copy the detail views of the modules.

Test: A frontend unit test presses a card entry and checks the route of the card.
