---
id: "000193"
title: A scroll edge fades, or cuts at a line
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-07
implementation:
  - frontend/vendor/ui-kit/src/lib/scroll-fade
  - frontend/vendor/ui-kit/src/styles/_scroll-fade.scss
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# A scroll edge fades, or cuts at a line

A scrolling pane must fade at its edges. Where a real line exists, for example a tab line on
the phone, the content must cut hard at that line. A list under a glass head (000527) does not fade.
Where the line is the lower edge of a glass head (000527), the content runs on under the line
as a blur.
