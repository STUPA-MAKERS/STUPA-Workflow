---
id: "000736"
title: The start and the end of an Event can have a time
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
implementation: null
scope:
  - backend/app/modules/todos
  - backend/app/modules/calendar
  - frontend/src/app/features/todos
---

# The start and the end of an Event can have a time

The start and the end of an Event (§F/collaboration/todos/000478) must each be a date with an
optional time. An Event without a time is an all-day entry. The end must not be before the
start. The card must show the times next to the dates, and the calendar feed must give a timed
Event with its times.

Reason: An Event such as a party or a lecture has a start time and an end time, and helpers
plan by them.

Test: A backend unit test sets a start with a time and an end with a time on an Event, reads
both back, and gets 422 for an end before the start.
