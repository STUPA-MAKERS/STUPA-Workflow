---
id: "003091"
title: One permission gives the link to pretix
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-25
implementation:
  - backend/app/shared/permissions.py
  - backend/app/modules/event_sales/router.py
scope:
  - backend/app/
  - frontend/src/app/
---
# One permission gives the link to pretix

The permission `pretix.use` (`Pretix nutzen`) must give the link of 003083 to a person who also writes the Event through
its team (003026). The read of the sales must need only the
read right on the Event. No seeded role except the admin role must hold `pretix.use`.

Reason: A link acts with the token of the platform in pretix. An admin gives this
on purpose, as for Paperless (002524).

Test: A backend unit test links a pretix event as a writer of the Event without `pretix.use` and
expects 403.
