---
id: "000467"
title: Concurrent card edits give 409
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/todos/service.py
  - backend/app/modules/todos/router.py
scope:
  - backend/app/modules/todos
---

# Concurrent card edits give 409

A card change with an old `version` must answer 409 `card_version_conflict`. A board read with
a matching weak ETag must answer 304.
