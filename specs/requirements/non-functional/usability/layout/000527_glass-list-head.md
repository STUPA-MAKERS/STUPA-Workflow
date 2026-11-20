---
id: "000527"
title: A list head is solid on a wide screen and glass on a phone
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
implementation:
  - frontend/src/app/pages/todos
  - frontend/vendor/ui-kit
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# A list head is solid on a wide screen and glass on a phone

On a wide screen the head of a list column must be solid in the page colour, without glass. The
head holds the title, the search bar, the filter chips and a pinned group head. The rows must
cut hard at the lower edge of the head. In the very high contrast mode (000605), the rows of the
column must lie in a frame with a white edge that starts below the head and ends with round
corners above the bottom edge of the screen.

On a phone the head of a list must be one frosted glass surface over the rows, as before. No
state of the scroll, a fast scroll too, must show a row sharp through the glass. Where the
glass reaches the top edge of the screen, it must turn into the solid page colour over 48 px,
unless the head sticks below another bar. The page
"To-Dos" follows this rule in "Alle", in "Liste" and below a board with rows. On a phone a board
shows one page per column under a tab line, and the head with the tab line is one frosted glass
surface over the page.

Reason: On a wide screen the glass showed blurred rows above the first row and asked for a fade
at the top edge of the screen. A solid head gives the rows a clear edge to cut at (000193). On a
phone the head is small, and the blur shows that the list continues.

Test: `frontend/vendor/ui-kit/src/lib/sticky-bar/sticky-bar.component.spec.ts` and screenshots of
a scrolled list on a wide screen and on a phone, in the light and the dark theme and in the very
high contrast mode.
