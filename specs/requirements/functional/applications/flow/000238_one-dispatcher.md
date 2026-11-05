---
id: "000238"
title: Every fire path runs the full action chain
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-05
scope:
  - backend/app/modules/flow
  - backend/app/shared/guards.py
  - backend/app/shared/config_schemas.py
  - backend/app/modules/voting
  - backend/app/modules/livevote
  - backend/worker
---

# Every fire path runs the full action chain

The manual route, the vote close, the live vote routes and the worker must use the same
action dispatcher. Use only the dependency `get_action_dispatcher`.
