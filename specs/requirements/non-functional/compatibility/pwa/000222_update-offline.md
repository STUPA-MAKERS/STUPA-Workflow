---
id: "000222"
title: The app shows update and offline bars
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - frontend/vendor/ui-kit/pwa/src/sw-update.service.ts
  - frontend/vendor/ui-kit/pwa/src/offline.service.ts
  - frontend/src/app/layout/shell.component.ts
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# The app shows update and offline bars

When a new version is ready, the app must show the update bar. Without network, it must show
the offline bar.
