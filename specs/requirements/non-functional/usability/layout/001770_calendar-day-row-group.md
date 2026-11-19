---
id: "001770"
title: The entries of the picked day are a row group without a frame
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
implementation:
  - frontend/src/app/features/calendar/calendar.component.html
  - frontend/src/app/features/calendar/calendar.component.scss
  - frontend/src/app/shared/ui/_very-high-contrast.scss
scope:
  - frontend/src/app/features/calendar
---

# The entries of the picked day are a row group without a frame

On a wide screen, the Kalender must show the entries of the picked day beside the grid as the
rows of one row group, like the list of the page Aktivität. The day must be the small-capital
label of the group. The column must not have a surface, a rounded frame or an inner padding of
its own. Each row must have the icon of the kind as its lead, the title, a line with the kind,
the time, the Gremium or calendar and the own answer to a Termin, and the chevron at its end.
The whole row must be pressable (000714).

In the very high contrast mode (000605), the column must not have the white edge, and a row
must not have an edge of its own beyond the edge of a row group.

Reason: A frame around cards of the same surface is a second list style beside the list of
Aktivität and the list of the phone Kalender. A person reads the entries of a day as one list.

Test: A frontend unit test picks a day and finds its entries as the rows of a row group with
the day as label. Style review of the Kalender in the light theme, the dark theme and the
display modes.
