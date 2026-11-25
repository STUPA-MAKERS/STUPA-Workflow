---
id: "003091"
title: One permission gives the write actions of pretix
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-25
implementation: null
scope:
  - backend/app/
  - frontend/src/app/
---
# One permission gives the write actions of pretix

The permission `pretix.use` (`Pretix nutzen`) must give the link of 003083 and the create of
003087, together with the write right on the Event. The read of the sales must need only the
read right on the Event. No seeded role except the admin role must hold `pretix.use`.

Reason: A link and a new shop act with the token of the platform in pretix. An admin gives this
on purpose, as for Paperless (002524).

Test: A backend unit test links a pretix event as a writer of the Event without `pretix.use` and
expects 403.
