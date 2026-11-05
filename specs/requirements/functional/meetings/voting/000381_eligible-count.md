---
id: "000381"
title: The eligible count comes from the roster
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/voting
  - backend/app/modules/livevote
---

# The eligible count comes from the roster

The server counts the eligible voters from the roster. It never uses the logged-in users or a
value from the client. A missing count fails the quorum.
