---
id: "000078"
title: Wait for a render with afterNextRender
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - frontend/
scope:
  - frontend/
---

# Wait for a render with afterNextRender

Code that waits for a render that a signal starts must use `afterNextRender`. It must not use
`setTimeout` from an event handler for this.

Reason: A timeout can fire before the render, so the first click fails.
