---
id: "000349"
title: Live data shows only aggregates
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/livevote/events.py
  - backend/app/modules/livevote/publisher.py
  - frontend/src/app/features/voting/beamer.component.ts
scope:
  - backend/app/modules/livevote
  - backend/app/modules/voting
---

# Live data shows only aggregates

The beamer and the tally events must show only counts, never a voter. While a vote is open,
they must show only the participation.
