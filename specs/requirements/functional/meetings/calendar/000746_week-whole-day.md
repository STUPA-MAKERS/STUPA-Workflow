---
id: "000746"
title: The week view shows the whole day from 00:00 to 24:00
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-12
tests:
  - "frontend/src/app/features/calendar/calendar-week/calendar-week.component.spec.ts:wholeDay"
implementation:
  - frontend/src/app/features/calendar/calendar-week/calendar-week.component.ts
  - frontend/src/app/features/calendar/calendar.util.ts
  - frontend/src/app/features/calendar/calendar-week/calendar-week.component.scss
scope:
  - frontend/src/app/features
---

# The week view shows the whole day from 00:00 to 24:00

The hour axis of the week view of the Kalender must show the 24 hours of the day. When the
view opens, 08:00 must be at the top of the hour grid. When an entry of the week starts before
08:00, the hour of the earliest such entry must be at the top instead. The time and the title of a
block must stay in view while the block starts above the visible hours.

Reason: On an axis from 08:00 to 21:00 the block of an entry over several days ends at the last
hour of the axis, and that looks as if the entry ended there. Only the whole day shows that it
goes on over the night.

Test: A frontend unit test checks that the axis has 24 hours, that the view opens at 08:00,
and that the block of a day between the first and the last day of an entry fills the 24 hours.
