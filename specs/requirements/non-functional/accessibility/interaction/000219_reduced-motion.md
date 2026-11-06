---
id: "000219"
title: Motion follows the reduced motion setting
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - frontend/vendor/ui-kit/src/styles/motion.scss
  - frontend/vendor/ui-kit/src/styles/_press.scss
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# Motion follows the reduced motion setting

With `prefers-reduced-motion`, the app must show no transitions, no slide and no press shrink.
