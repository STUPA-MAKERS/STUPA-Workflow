---
id: "000594"
title: A display setting overrides the system setting
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-10
implementation: null
scope:
  - frontend/src/app/features/help
  - frontend/vendor/ui-kit
---

# A display setting overrides the system setting

Each switch of 000593 must show the state that is in effect. Without a choice of the person,
that is the state of the system setting (`prefers-contrast`, `prefers-reduced-motion`,
`prefers-reduced-transparency`). When the person sets a switch, the choice must override the
system setting on this device and must stay after a reload. The entry "Systemeinstellungen
verwenden" must remove every choice of the group, and it must show only while a choice
exists.

Reason: The system setting is the right default. Some people cannot change it, for example
on a shared or a managed computer.

Test: `frontend/vendor/ui-kit/src/lib/display/display-settings.service.spec.ts`.
