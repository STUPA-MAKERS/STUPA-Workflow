---
id: "003085"
title: The worker reads the pretix sales
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-25
implementation:
  - backend/app/modules/event_sales/pretix_sync.py
  - backend/app/modules/event_sales/router.py
  - backend/worker/event_sales.py
scope:
  - backend/app/
  - frontend/src/app/
  - backend/worker
---
# The worker reads the pretix sales

A worker cron must read the sales of each linked pretix event every 15 minutes while the Event
is in the phase `open` (003036) or its end is at most 30 days ago. A person who writes the Event
must have the action `Aktualisieren`, which reads the sales at once, at most once per minute
for an Event. The platform must not receive webhooks from pretix. A failed read must keep the
last sales and show the time of the last read that worked.

Reason: A webhook of pretix has no signature, so the platform must read the order again in any
case. A read by the worker needs no public route and no secret, and 15 minutes are current
enough for the planning of an Event.

Test: A backend unit test runs the cron with a fake pretix and reads the new sums, and runs it
with a pretix that fails and reads the old sums.
