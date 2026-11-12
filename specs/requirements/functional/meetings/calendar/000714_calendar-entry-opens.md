---
id: "000714"
title: An entry opens its own element
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
implementation:
  - frontend/src/app/features/calendar/calendar.component.ts
  - frontend/src/app/features/calendar/external-entry/external-entry.component.ts
scope:
  - frontend/src/app/features
---

# An entry opens its own element

The side panel of the desktop must show each entry of the picked day as one card that is
pressable as a whole. A meeting entry must open the meeting and a card entry must open the card.
A Termin and an entry of an external calendar must open in a dialog on the desktop and in a
bottom sheet on the phone. The dialog of an external entry must be read-only and must show the
title, the time, the place, the description and the name of the calendar.

Reason: The Kalender does not copy the detail views of the modules.

Test: A frontend unit test presses a card entry and checks the route of the card.
