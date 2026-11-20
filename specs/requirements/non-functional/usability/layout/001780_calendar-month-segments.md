---
id: "001780"
title: Each day of the month grid is a segment of its own
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
implementation:
  - frontend/src/app/features/calendar/calendar.component.scss
  - frontend/src/app/shared/ui/_very-high-contrast.scss
scope:
  - frontend/src/app/features/calendar
---

# Each day of the month grid is a segment of its own

On a wide screen, each day cell of the Kalender month grid must be a segment of its own, like a
row of a row group. The segments must stand 2px apart, with the page between them, and must have
no grid lines. The inner corners of a segment must have a 4px radius. Only the four outer
corners of the month (the first and the last day of the first and the last week) must have the
large radius of a row group. The grid must not have a surface or a frame of its own behind the
segments. A day of the month must keep surface 1 and a day of another month surface 2. The row
of the weekday names must stay plain text above the segments. A bar of an entry over several
days must go across the gaps.

In the very high contrast mode (000605), the segments must stand 8px apart, every corner must
have the large radius, and each segment must have the white edge. The grid must not have the
white edge around the whole month.

The week view keeps its surface and its lines.

Reason: The day list beside the grid is a row group (001770). A grid with lines on one surface
is a second style beside it. Segments make the page read as one style, like the segmented
surfaces of the app.

Test: Style review of the Kalender month grid in the light theme, the dark theme and the display
modes.
