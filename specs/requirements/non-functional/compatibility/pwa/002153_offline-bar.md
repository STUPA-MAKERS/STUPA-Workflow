---
id: "002153"
title: The app shows the offline bar
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
tests:
  - "frontend/vendor/ui-kit/pwa/src/offline.service.spec.ts:OfflineService"
implementation:
  - frontend/vendor/ui-kit/pwa/src/offline.service.ts
  - frontend/src/app/layout/shell.component.ts
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# The app shows the offline bar

Without network, the app must show the offline bar.

Reason: The person must know why a page does not load or save.

Test: The kit test of `OfflineService` sets the browser offline and expects the bar.
