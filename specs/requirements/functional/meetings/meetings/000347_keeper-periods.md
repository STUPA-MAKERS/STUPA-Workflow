---
id: "000347"
title: A keeper period follows the current TOP
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/livevote
  - backend/app/modules/protocol
scope:
  - backend/app/modules/livevote
  - backend/app/modules/protocol
---

# A keeper period follows the current TOP

A move to a later TOP must start the planned keeper period in the same transaction. The meeting
must always name the keeper of the running period.
