---
id: "001315"
title: A pressed segment ripples only inside its segment
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
implementation:
  - frontend/vendor/ui-kit/src/styles/_press.scss
  - frontend/vendor/ui-kit/src/lib/segmented/segmented.component.scss
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# A pressed segment ripples only inside its segment

The ripple of a pressed segment of a segmented control (001314) must stay inside that segment
and inside the rounded track. The control must not shrink.

Reason: A ripple that crosses into the next segment reads as a press on two choices.

Test: `touch.spec.ts` of the ui-kit reads the press of the segmented control.
