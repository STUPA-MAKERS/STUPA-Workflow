---
id: "002002"
title: The app runs its change detection without zone.js
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
tests:
  - "frontend/src/app/zoneless.contract.spec.ts:zonelessContract"
implementation:
  - frontend/src/app/app.config.ts
  - frontend/angular.json
scope:
  - frontend/src/app
  - frontend/angular.json
---

# The app runs its change detection without zone.js

The app must use the zoneless change detection of Angular. The build must not load the
zone.js polyfill. A component must show a change through a signal, a template event, the async
pipe or `markForCheck`.

Reason: With zone.js each scroll event, timer and animation frame checked the whole app. The
scroll handlers of the list heads ask for a frame on each scroll event, so a phone checked the
app several times per frame while it scrolled. Without zone.js the bundle is also 35 kB smaller.

Test: A contract test reads `angular.json` and fails when a build loads `zone.js`. It reads the
root providers and fails without `provideZonelessChangeDetection()`.
