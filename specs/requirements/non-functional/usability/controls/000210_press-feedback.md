---
id: "000210"
title: A press gives feedback
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - frontend/vendor/ui-kit/src/styles/_press.scss
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# A press gives feedback

Every clickable element must shrink on press, with the press tint: controls to 0.94, rows and
cards to 0.98. Prose links and text inputs must not shrink. With reduced motion, nothing must
shrink. A segment of a segmented control shrinks with its whole control (000528).
