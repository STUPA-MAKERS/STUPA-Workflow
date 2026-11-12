---
id: "000744"
title: A timed entry over several days is a block on each of its days in the week view
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-12
tests:
  - "frontend/src/app/features/calendar/calendar-week/calendar-week.component.spec.ts:spanBlocks"
implementation:
  - frontend/src/app/features/calendar/calendar.util.ts
  - frontend/src/app/features/calendar/calendar-week/calendar-week.component.ts
scope:
  - frontend/src/app/features
---

# A timed entry over several days is a block on each of its days in the week view

The week view of the Kalender must show an entry over several days that has a start time as a
block in the hour grid of each of its days. The block of the first day must go from the start
time to the last hour of the axis. The block of a day between must fill the axis. The block of
the last day must go from the first hour of the axis to the end time. Only an entry without a
start time and a due card must be in the row above the hours.

Reason: The row above the hours hides the times of an entry. An Event from Tuesday 14:00 to
Thursday 12:00 leaves Tuesday morning free, and only a block shows that.

Test: A frontend unit test gives the week view an entry from Tuesday 14:00 to Thursday 12:00
and checks that each of the three days has a block and that the row above the hours has none.
