---
id: "000091"
title: A signal update returns a new value
kind: style
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - frontend/src/app/
  - ui-kit
---

# A signal update returns a new value

A `computed()` body is a pure expression. The function of `.update()` returns a new value.
Do not copy a value and then mutate the copy.

Reason: Angular compares by reference, so an in-place change does not render.
