---
id: "000237"
title: Actions run after the commit and never undo it
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - backend/app/modules/flow
  - backend/app/shared/guards.py
  - backend/app/shared/config_schemas.py
scope:
  - backend/app/modules/flow
  - backend/app/shared/guards.py
  - backend/app/shared/config_schemas.py
---

# Actions run after the commit and never undo it

Worker actions run after the commit. Each action is idempotent and has a stable idempotency
key. A failed action is logged and must not roll back the state change.
