---
id: "000333"
title: A calendar event has a reminder
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/calendar
scope:
  - backend/app/modules/calendar
---

# A calendar event has a reminder

A meeting without a valid end must last 1 hour. Each event must have a reminder 1 hour before a
timed event, or 1 day before an all-day event.
