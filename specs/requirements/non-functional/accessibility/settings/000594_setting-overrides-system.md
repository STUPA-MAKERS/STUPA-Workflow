---
id: "000594"
title: A display setting overrides the system setting
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
tests:
  - "frontend/vendor/ui-kit/src/lib/display/display-settings.service.spec.ts:DisplaySettingsService"
implementation:
  - frontend/vendor/ui-kit/src/lib/display/display-settings.service.ts
  - frontend/src/app/features/help/help-menu
scope:
  - frontend/src/app/features/help
  - frontend/vendor/ui-kit
---

# A display setting overrides the system setting

Each switch of 000593 that has a system setting must show the state that is in effect. Without a choice of the person,
that is the state of the system setting (`prefers-color-scheme`, `prefers-contrast`,
`prefers-reduced-motion`, `prefers-reduced-transparency`). When the person sets a switch, the
choice must override the system setting in this browser on this device, and it must stay after
a reload. The choice must not be stored in the account. The entry "Systemeinstellungen
verwenden" must remove every choice of the group, and it must show only while a choice exists.

Reason: The system setting is the right default. Some people cannot change it, for example
on a shared or a managed computer.

Test: `frontend/vendor/ui-kit/src/lib/display/display-settings.service.spec.ts`.
