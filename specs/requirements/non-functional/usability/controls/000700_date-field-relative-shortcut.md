---
id: "000700"
title: A date field takes a shortcut relative to today
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-11
implementation: null
scope:
  - frontend/vendor/ui-kit/src/lib/datepicker
  - frontend/src/app/
---

# A date field takes a shortcut relative to today

A date field must accept a shortcut that names a date relative to today. A shortcut is one or
more terms. Each term is a sign `+` or `-`, a whole number and a unit. The units are `d` or `t`
(day), `w` (week), `m` (month) and `y` or `j` (year). Upper case and spaces must be accepted,
so `+1w`, `-1d`, `+ 2 W` and `+1m-2d` are shortcuts. Today is the local date of the device.

Reason: A person who sets a due date or a meeting date mostly counts from today. To type
`+1w` is faster than to find the date in the calendar.

Test: A unit test of the date field types `+1w`, `-1d`, `+1y`, `+1m-2d` and `+ 2 W` with a
fixed today and expects the ISO date of each.
