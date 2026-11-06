---
id: "000091"
title: A signal update returns a new value
kind: style
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - frontend/src/app/
  - frontend/vendor/ui-kit
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# A signal update returns a new value

A `computed()` body must be a pure expression. The function of `.update()` must return a new
value. Code must not copy a value and then mutate the copy.

Reason: Angular compares by reference, so an in-place change does not render.
