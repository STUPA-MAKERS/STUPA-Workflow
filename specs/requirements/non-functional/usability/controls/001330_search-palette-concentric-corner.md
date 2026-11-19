---
id: "001330"
title: The search window has a corner concentric with its search bar
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
implementation:
  - frontend/vendor/ui-kit/shell/src/command-palette/command-palette.component.scss
scope:
  - frontend/vendor/ui-kit/shell/src/command-palette
---

# The search window has a corner concentric with its search bar

The corner radius of the search window (Strg+K) must be the radius of its search bar plus
the inset of the bar: half of `--control-height-lg` plus `--space-3` (38px). The same
radius must apply on a phone and on a wider screen.

Reason: The search bar is a pill that sits inset in the window. With one even gap between
the window edge and the pill, the two curves look like one shape. The dialog radius of 24px
(20px on a phone) was smaller than the pill radius of 26px, so the corner looked too
sharp around the pill.

Test: Review of the screenshots. No automated test reads the computed radius.
