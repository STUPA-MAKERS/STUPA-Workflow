---
id: "000219"
title: Motion follows the reduced motion setting
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
tests:
  - "frontend/vendor/ui-kit/src/styles/display-settings.spec.ts:settingsFollowChoice"
implementation:
  - frontend/vendor/ui-kit/src/styles/motion.scss
  - frontend/vendor/ui-kit/src/styles/_press.scss
  - frontend/vendor/ui-kit/src/styles/_display.scss
  - frontend/vendor/ui-kit/src/lib/motion/motion.ts
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# Motion follows the reduced motion setting

With `prefers-reduced-motion`, or with the switch "Weniger Bewegung" on (000593), the app must
show no transitions, no slide and no press shrink. With the switch off, the app must show the
motion also when the system asks for reduced motion (000594).
