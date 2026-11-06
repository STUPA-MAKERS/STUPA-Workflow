---
id: "000346"
title: A meeting opens only with a protokollant
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/livevote/service/lifecycle.py
scope:
  - backend/app/modules/livevote
---

# A meeting opens only with a protokollant

A meeting must go from `planned` to `live` only when it has a protokollant, else 409.
