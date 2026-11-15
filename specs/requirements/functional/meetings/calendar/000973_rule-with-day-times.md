---
id: "000973"
title: A recurrence rule with times of the day gives only the first date
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
implementation:
  - backend/app/modules/calendar/external_feed.py
scope:
  - backend/app/modules/calendar
---

# A recurrence rule with times of the day gives only the first date

A recurring event of an external calendar whose rule has `BYHOUR`, `BYMINUTE` or `BYSECOND`
must give only its first date, like a rule with a frequency below a day
(§F/meetings/calendar/000723).

Reason: Such a rule makes up to 86 400 dates for each day. The reader walks each date from the
start of the series to the window, so a start many years back stops the worker.

Test: A backend unit test reads a daily rule with `BYHOUR`, `BYMINUTE` and `BYSECOND` and a
start in the year 1900, and finds one entry.
