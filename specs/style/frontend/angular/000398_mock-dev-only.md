---
id: "000398"
title: The mock API runs only in dev builds
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - frontend/src/app/app.config.ts
scope:
  - frontend/src/app/
---

# The mock API runs only in dev builds

The mock interceptor must be registered only when `isDevMode()` is true.
