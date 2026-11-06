---
id: "000351"
title: A join code is short and unambiguous
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/livevote/guests.py
scope:
  - backend/app/modules/livevote
---

# A join code is short and unambiguous

The join code must have 6 characters from `ABCDEFGHJKMNPQRSTUVWXYZ23456789`. It must be unique
among meetings that are not closed. A rotation must void the open requests. Admitted guests
must keep their access.
