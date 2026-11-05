---
id: "000398"
title: The mock API runs only in dev builds
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - frontend/src/app/
---

# The mock API runs only in dev builds

The mock interceptor is registered only when `isDevMode()` is true.
