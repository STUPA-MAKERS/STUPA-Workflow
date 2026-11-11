---
id: "000710"
title: The Kalender is its own tab
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
implementation: null
scope:
  - frontend/src/app/features
  - frontend/src/app/layout
  - frontend/src/app/features/meetings
---

# The Kalender is its own tab

The app must have the navigation entry `Kalender` (`Calendar`) with the route `/calendar`, after
`Boards`. Each signed-in person must see the entry. Sitzungen must show only the list and must
not have the switch `Liste | Kalender`. The `Kalender-Abo` popover must be on the Kalender page.

Reason: The dates of a person come from meetings, cards, Termine and external calendars. One
page must show them together, and a second month grid in Sitzungen would show a part of them.

Test: A frontend unit test finds the entry in the navigation of a person without a Gremium. A
frontend unit test finds no view switch on Sitzungen.
