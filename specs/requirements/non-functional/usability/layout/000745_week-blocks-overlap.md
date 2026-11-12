---
id: "000745"
title: A later entry lies on an earlier one in the week view
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-12
tests:
  - "frontend/src/app/features/calendar/calendar-week/calendar-week.component.spec.ts:overlap"
implementation:
  - frontend/src/app/features/calendar/calendar.util.ts
  - frontend/src/app/features/calendar/calendar-week/calendar-week.component.scss
scope:
  - frontend/src/app/features
---

# A later entry lies on an earlier one in the week view

Two blocks of the week view of the Kalender that overlap in time must each take a lane of the
day column. A block must grow to the right over the lanes that are free beside it. When the
block in the next lane starts 45 minutes or more after it, the earlier block must reach to the
end of the day column below that block, and the later block must lie on it with an edge in the
colour of the grid. Two blocks that start less than 45 minutes apart must stay side by side.

Reason: Lanes of equal width make each block narrow, and the title of a long entry breaks into
single syllables. A later block that lies on an earlier one leaves the time and the title of
the earlier one readable, as calendar apps commonly do. The time and the first line of the
title take 45 minutes of the height of a block. A block that starts earlier than that after
another would hide them, so those two stay side by side.

Test: A frontend unit test gives the week view an entry from 14:00 to 15:30 and one from 14:45
to 15:15 and checks that the first has the width of the day and that the second lies above it.
