---
id: "001331"
title: The scroll part of the navigation rail is a surface
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
implementation:
  - frontend/vendor/ui-kit/shell/src/nav-rail/nav-rail.component.scss
  - frontend/vendor/ui-kit/src/styles/display-settings.scss
scope:
  - frontend/vendor/ui-kit/shell
---

# The scroll part of the navigation rail is a surface

The part of the navigation rail that scrolls must lie on a surface with rounded corners, 24 px
narrower than the rail. The items must cut hard at the edge of that surface and must not fade.
In the very high contrast mode (000605), the surface must have a white edge that keeps clear of
the line between the rail and the page.

Reason: The fade of the rail was the last fade in the frame of the app. A surface gives the
items an edge to cut at, as every other scroll area has (000193).

Test: Screenshots of the rail with more items than fit, in the light and the dark theme and in
the very high contrast mode.
