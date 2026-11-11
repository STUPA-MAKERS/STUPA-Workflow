---
id: "000702"
title: A month or year shortcut stops at the end of the month
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-11
implementation: null
scope:
  - frontend/vendor/ui-kit/src/lib/datepicker
---

# A month or year shortcut stops at the end of the month

A `m` or `y` term (000700) must keep the day of the month. When the target month has fewer
days, the date must be the last day of the target month. So 31.01.2026 `+1m` is 28.02.2026 and
29.02.2028 `+1y` is 28.02.2029. The terms must apply from left to right.

Reason: A plain day overflow makes 31.01. `+1m` into 03.03., which is in the wrong month.

Test: A unit test with today 31.01.2026 expects `+1m` to give 2026-02-28, and with today
29.02.2028 expects `+1y` to give 2029-02-28.
