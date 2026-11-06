---
id: "000381"
title: The eligible count comes from the roster
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/voting/service.py
  - backend/app/modules/livevote/roster.py
scope:
  - backend/app/modules/voting
  - backend/app/modules/livevote
---

# The eligible count comes from the roster

The server must count the eligible voters from the roster. It must never use the logged-in
users or a value from the client. A missing count must fail the quorum.
