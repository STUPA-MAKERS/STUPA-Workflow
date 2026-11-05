---
id: "000239"
title: A transition into a vote state can add the Antrag to a meeting
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/flow
  - backend/app/shared/guards.py
  - backend/app/shared/config_schemas.py
  - backend/app/modules/livevote
---

# A transition into a vote state can add the Antrag to a meeting

A transition with `addToNextSession` into a vote state can name a planned meeting of the
action Gremium. Then the TOP is added in the same transaction. Without a meeting, the worker
adds the Antrag to the earliest planned meeting from today on. A live or closed meeting never
gets the TOP.
