---
id: "001946"
title: The Kalender filter chips stand in a row of their own below the search
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
implementation:
  - frontend/src/app/features/calendar/calendar.component.html
  - frontend/src/app/features/calendar/calendar.component.scss
scope:
  - frontend/src/app/features/calendar
---

# The Kalender filter chips stand in a row of their own below the search

On a wide screen, the search pill of the Kalender must be exactly as wide as the calendar area
(the column of the month or week grid). It must not reach over the day list beside the grid.
The filter chips (Art, Gremium, Zuständig) must stand in a row of their own directly below the
search pill, aligned at its start edge, like the chips of the other lists and of the Kalender
on the phone. A filter chip must never stand on the same line as the search pill.

Reason: The search pill is 44px high and a filter chip is 32px high (001892). On one line, the
two heights clash and the row looks broken. The chips are kept at 32px, because one control
with one job has one look.

Test: Screenshots of the desktop Kalender in light, dark and very high contrast show the search
pill on its own line, with the same width as the grid, and the chips in the row below it.
