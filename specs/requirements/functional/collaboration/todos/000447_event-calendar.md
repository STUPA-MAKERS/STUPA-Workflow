---
id: "000447"
title: An Event with a start is in the calendar
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-06
scope:
  - backend/app/modules/todos
  - frontend/src/app/features/todos
  - backend/app/modules/calendar
---

# An Event with a start is in the calendar

An Event with a start must be an entry in the calendar feed of each person who can read its
board. An Event without an end lasts one day.

Reason: The members of the Gremium see the Events beside the meetings.

Test: A backend unit test reads an Event from the calendar feed.
