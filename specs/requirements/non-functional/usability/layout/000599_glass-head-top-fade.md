---
id: "000599"
title: A glass list head fades into the page colour at the top screen edge
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
implementation:
  - frontend/vendor/ui-kit/src/styles/_frosted.scss
  - frontend/vendor/ui-kit/src/styles/list-detail.scss
  - frontend/vendor/ui-kit/src/lib/sticky-bar/sticky-bar.component.scss
  - frontend/vendor/ui-kit/src/lib/list-group/list-group.component.scss
scope:
  - frontend/vendor/ui-kit
---

# A glass list head fades into the page colour at the top screen edge

Where the glass of a list head (000527) reaches the top edge of the screen, the glass must
turn into the solid page colour at that edge over 48 px. This applies to every list head: the
head of a list column on a wide screen, the search bar of a list on a phone, and a group head
that carries the glass of the head. The sides of the glass keep their fade into the page
colour. Where the head sticks below another bar, the glass must not fade at its top, because
that bar is the edge.

Reason: Rows that scroll up under the head show as a blur up to the top edge of the screen,
and there they cut sharp at the edge of the screen. The fade lets them run out into the page
colour, as the sides of the glass already do.

Test: Screenshots of a list with rows scrolled under the head (Verwaltung, Anträge) on a phone
and on a desktop width, in the light and the dark theme.
