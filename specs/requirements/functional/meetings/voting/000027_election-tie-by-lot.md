---
id: "000027"
title: A tie in an election is decided by lot
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/voting/election.py
scope:
  - backend/app/modules/voting
  - frontend/src/app/features/voting
---

# A tie in an election is decided by lot

A tie at the seat limit of a personnel election must be decided by lot. The platform must draw
the lot. There must be no runoff route. A stored result with `runoff` must still show.
