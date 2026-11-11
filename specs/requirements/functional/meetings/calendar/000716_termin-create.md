---
id: "000716"
title: Each signed-in person creates a Termin
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-11
implementation: null
scope:
  - backend/app/modules/calendar
  - frontend/src/app/features
---

# Each signed-in person creates a Termin

Each signed-in person must be able to create a Termin from the Kalender. Only the creator and
a person with the permission `calendar.manage` must be able to change or delete it.

Reason: A Termin without invited persons is private, so the creation needs no permission.

Test: A backend unit test changes a Termin as an invited person and gets 403.
