---
id: "000075"
title: A template narrows a signal with as
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - frontend/
scope:
  - frontend/
---

# A template narrows a signal with as

A template must narrow a signal with `@if (value(); as v)` and must use `v`. It must not call
the signal again after `@if (value())`.

Reason: strict templates do not narrow a second call.
