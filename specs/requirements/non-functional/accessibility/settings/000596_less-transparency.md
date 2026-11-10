---
id: "000596"
title: Less transparency makes the glass surfaces opaque
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
tests:
  - "frontend/vendor/ui-kit/src/styles/display-settings.spec.ts:lessTransparency"
implementation:
  - frontend/vendor/ui-kit/src/styles/display-settings.scss
  - frontend/vendor/ui-kit/src/styles/_frosted.scss
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# Less transparency makes the glass surfaces opaque

With `prefers-reduced-transparency: reduce`, or with the switch "Weniger Transparenz" on,
every frosted surface must be opaque and must show no blur.

Reason: Content that shows through a bar or a sheet makes its text harder to read.

Test: `frontend/vendor/ui-kit/src/styles/display-settings.spec.ts`.
