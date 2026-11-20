---
id: "002010"
title: Bars and heads are solid, and only floating boxes are glass
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
tests:
  - "frontend/vendor/ui-kit/src/styles/styles.spec.ts:SolidBars"
implementation:
  - frontend/vendor/ui-kit/src/styles/_frosted.scss
  - frontend/vendor/ui-kit/src/styles/tokens.scss
  - frontend/vendor/ui-kit/src/styles/list-detail.scss
  - frontend/vendor/ui-kit/shell/src/bottom-bar/bottom-bar.component.scss
  - frontend/vendor/ui-kit/src/lib/sticky-bar/sticky-bar.component.scss
  - frontend/vendor/ui-kit/src/lib/list-group/list-group.component.scss
  - frontend/vendor/ui-kit/src/lib/list-detail/list-detail-bar.component.scss
  - frontend/vendor/ui-kit/src/lib/tab-pager/tab-pager.component.scss
  - frontend/src/app/layout/public-header/public-header.component.scss
  - frontend/src/app/features/public-meeting/public-meeting.component.scss
  - frontend/src/app/pages/todos
  - frontend/src/app/features/meetings/top-sheet/top-sheet.component.scss
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# Bars and heads are solid, and only floating boxes are glass

A bar or a head that content scrolls under must be solid, without blur and without see-through
tint. This applies on a phone and on a wide screen to the phone navigation bar, the bar of a
detail, the search bar of a list, the head of a list column, a pinned group head, a tab line
that sticks and the bar of a public page.

At rest such a head must have the colour of the surface it sits on. While content is under it
(the page or the rows have scrolled), the head must take the bar colour (surface 3, the colour
of the navigation bar). A head and a tab line or a group head that stick right under it must
take the bar colour together, so they read as one head.

The navigation bar and the heads must not cast a shadow. The step in colour marks the edge. In
the very high contrast mode (000605) every surface is black, so a scrolled head must end in the
white edge of a surface, and the navigation bar keeps its white line at the top.

Only a box that floats over the page keeps the frosted glass: a dialog, a side sheet, a bottom
sheet, a menu, a popover, a toast and a floating dock (the dock of a Sitzung, the ballot bar).
The setting for less transparency (000596) still makes these boxes solid.

Reason: The glass of the bars cost time on every frame of a scroll on a phone, showed seams
where two layers of glass met, and turned see-through during a view transition. A solid bar
with a change of colour looks cleaner and shows the scrolled state without a shadow.

Test: A unit test of the kit styles finds no backdrop filter, no glass mixin and no shadow in
the bars, and the bar colour in their scrolled state. Screenshots of a list, a detail and a
Sitzung, at rest and scrolled, on a phone and on a wide screen, in the light and the dark theme
and in the very high contrast mode.
