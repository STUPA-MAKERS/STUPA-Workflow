---
id: "000078"
title: Wait for a render with afterNextRender
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - frontend/
---

# Wait for a render with afterNextRender

Use `afterNextRender` to wait for a render that a signal starts. Do not use `setTimeout` from
an event handler for this.

Reason: A timeout can fire before the render, so the first click fails.
