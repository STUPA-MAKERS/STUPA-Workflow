---
id: "000722"
title: The worker fetches external calendars
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
implementation: null
scope:
  - backend/app/modules/calendar
  - backend/worker
---

# The worker fetches external calendars

The worker must fetch each external calendar at the interval that the admin set for it and after
each save of its URL. The interval must be one of 15 minutes, 1 hour, 6 hours and 24 hours, and a
new calendar must start with 1 hour.
The fetch must go through the SSRF guard, must follow no redirect to another host without a new
guard check, and must stop at 2 MB or 10 seconds. A failed fetch must keep the entries of the last
good fetch, and the admin page must show the time and the cause of the failure. The API must
never fetch an external URL in a request of a person.

Reason: An external URL is input of an admin, and the server must not reach internal hosts with
it. A slow source must not slow a page.

Test: A backend unit test gives a URL that resolves to a private address and finds no request.
A backend unit test fails a fetch and still reads the old entries.
