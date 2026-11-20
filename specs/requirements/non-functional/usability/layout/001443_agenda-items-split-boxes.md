---
id: "001443"
title: The TOPs beside the protocol are split boxes like the agenda head
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
implementation:
  - frontend/src/app/features/meetings/agenda-pane/agenda-pane.component.scss
scope:
  - frontend/src/app/features/meetings
---

# The TOPs beside the protocol are split boxes like the agenda head

On a wide screen each TOP in the agenda column of a Sitzung must be a split box with the shape
of the agenda head (001440): the item on one surface and its ⋮ menu on a second surface beside
it, in the column of the add segment. The boxes must have a 3 px gap and small inner corners.
The last TOP must have large corners at the bottom. The box of the menu must always show. On a
device with hover, the ⋮ in it must show only while the pointer is on the TOP, while the TOP
holds the keyboard focus, or while its menu is open. On a touch screen, the ⋮ must always show.
The ⋮ must keep the text colour, also on hover. In the very high contrast mode (000605), each
surface must have a white edge.

Reason: The head and the list had two different shapes. As split boxes, the TOPs repeat the
shape of the head. The ⋮ of every TOP at once was noisy, so it shows for the TOP in use.

Test: Screenshots of a live Sitzung with a long agenda on a wide screen, in the light and the
dark theme and in the very high contrast mode.
