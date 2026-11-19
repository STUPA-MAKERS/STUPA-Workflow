---
id: "001350"
title: The agenda beside the protocol is a split head over its list
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
implementation:
  - frontend/src/app/features/meetings/agenda-pane/agenda-pane.component.scss
  - frontend/src/app/features/meetings/meeting-page/meeting-page.component.scss
scope:
  - frontend/src/app/features/meetings
---

# The agenda beside the protocol is a split head over its list

On a wide screen the agenda column of a Sitzung must have three surfaces: a title segment, an
add segment beside it, and the list of TOPs below both. The surfaces must have a 3 px gap and
small inner corners, as the segments of a split button. Only the list must scroll, so the title
and the add button stay in view. The content of the Sitzung must keep 12 px of space to the
navigation rail. In the very high contrast mode (000605), each segment must have a white edge,
and the add segment must be black with a yellow plus.

Reason: The title and the add button were part of the scroll area and went out of view. As
segments of their own they stay pinned, and the list cuts at the edge of its surface (000193).

Test: Screenshots of a live Sitzung with a long agenda on a wide screen, in the light and the
dark theme and in the very high contrast mode.
