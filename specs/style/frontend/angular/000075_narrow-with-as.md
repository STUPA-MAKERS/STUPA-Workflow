---
id: "000075"
title: A template narrows a signal with as
kind: style
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - frontend/
---

# A template narrows a signal with as

Write `@if (value(); as v)` and use `v`. Do not call the signal again after `@if (value())`.

Reason: strict templates do not narrow a second call.
