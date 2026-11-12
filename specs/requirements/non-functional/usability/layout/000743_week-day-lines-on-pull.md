---
id: "000743"
title: The day lines of the week grid stay when the hours are pulled
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-12
tests:
  - "frontend/src/app/features/calendar/calendar-week/calendar-week.component.spec.ts:dayLinesOnPull"
implementation:
  - frontend/src/app/features/calendar/calendar-week/calendar-week.component.scss
scope:
  - frontend/src/app/features
---

# The day lines of the week grid stay when the hours are pulled

The scroll area of the week grid of the Kalender must draw the vertical lines between the days
itself. A pull past the first or the last hour must not show an area without these lines.

Reason: A pull moves the hour columns away from the all-day row. Without lines of its own the
area between them is a band that cuts each day line.

Test: `calendar-week.component.spec.ts` reads the styles and fails when the scroll area has no
line pattern.
