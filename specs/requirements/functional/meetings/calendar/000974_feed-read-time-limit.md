---
id: "000974"
title: The read of an external feed has a time limit
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
implementation:
  - backend/app/modules/calendar/external.py
  - backend/app/modules/calendar/external_feed.py
scope:
  - backend/app/modules/calendar
  - backend/worker
---

# The read of an external feed has a time limit

The worker must read the bytes of an external feed in a process of its own. The worker must
stop that process after 10 seconds and must store the failure with the cause `timeout`. The
entries of the last good fetch must stay (F/meetings/calendar/000722).

Reason: The feed is the input of another system. A read that never ends in the worker process
stops each other job of the worker: mails, virus scans, backups and deadlines.

Test: A backend unit test gives a reader that never returns, and finds the cause `timeout` and
the old entries after the limit.
