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
The last TOP must have large corners at the bottom. On a device with hover, the split, the box
of the menu and the ⋮ in it must show only while the pointer is on the TOP, while the TOP holds
the keyboard focus, or while its menu is open. At rest the TOP must be one box over the full
width, and its title must use the full width of that box. The title must give room to the
menu only while the ⋮ shows. On a touch screen, the split and the ⋮
must always show.
The ⋮ must keep the text colour, also on hover. In the very high contrast mode (000605), each
surface must have a white edge, the chosen TOP must be yellow up to its outer edge, and the box
of its menu must have the same outer height and the same 3 px gap as on every other TOP.

Reason: The head and the list had two different shapes. As split boxes, the TOPs repeat the
shape of the head. The split and the ⋮ of every TOP at once were noisy, so they show for the TOP in use. Room
kept for a hidden ⋮ cut the titles short at rest.

Test: Screenshots of a live Sitzung with a long agenda on a wide screen, in the light and the
dark theme and in the very high contrast mode.
