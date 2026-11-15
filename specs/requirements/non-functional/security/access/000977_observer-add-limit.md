---
id: "000977"
title: Adding observers has a rate limit
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
implementation:
  - backend/app/shared/antiabuse.py
  - backend/app/modules/applications/observers_router.py
scope:
  - backend/app/shared/antiabuse.py
  - backend/app/modules/applications
---

# Adding observers has a rate limit

The add of an observer must count against `rl_observers_per_hour` (10) for each Antrag. Over
the limit the route must answer 429 with `Retry-After`. A removed observer must not give the
count back.

Reason: Each add sends a mail to a free address, and an applicant session is enough for it
(F/applications/applications/000754). The limit of five observers counts only the current
ones, so add and remove in a loop sends mails without an end.

Test: A backend unit test adds and removes observers of one Antrag and finds 429 at the add
after the limit.
