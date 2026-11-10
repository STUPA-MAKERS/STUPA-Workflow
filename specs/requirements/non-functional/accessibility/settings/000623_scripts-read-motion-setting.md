---
id: "000623"
title: A script reads the motion setting, not the system
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-10
tests:
  - "frontend/vendor/ui-kit/src/styles/display-settings.spec.ts:scriptsReadMotionSetting"
implementation:
  - frontend/vendor/ui-kit/src/lib/motion/motion.ts
  - frontend/vendor/ui-kit/src/lib/data-table/data-table.component.ts
  - frontend/vendor/ui-kit/src/lib/focus/first-invalid.ts
  - frontend/src/app/pages/applications/applications-detail.component.ts
  - frontend/src/app/pages/admin/forms/form-editor.component.ts
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# A script reads the motion setting, not the system

A script that moves or scrolls content must ask `reducedMotion()` of the kit. It must not read
`prefers-reduced-motion` itself. While less motion is in effect (000219), a scroll that a script
starts must be instant.

Reason: A script that reads the system does not follow the switch "Weniger Bewegung" (000594), and
a smooth scroll moves the whole page.

Test: `frontend/vendor/ui-kit/src/styles/display-settings.spec.ts` searches the sources of the kit
and of the app. It fails on `prefers-reduced-motion` outside the display service and on `behavior:
'smooth'` without `reducedMotion()`.
