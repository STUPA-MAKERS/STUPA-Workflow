---
id: "002502"
title: Only urgent kinds push by default
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
implementation:
  - backend/app/modules/notifications
  - frontend/src/app/pages/account
scope:
  - backend/app/modules/notifications
  - backend/worker/push.py
  - frontend/src/app/core/pwa
  - frontend/src/app/pages/account
---

# Only urgent kinds push by default

After a person switches on push, only these kinds must be on: mention (`mention`,
`todo_mentioned`), to-do assigned (`todo_assigned`), poll started (`poll_started`) and meeting
(`meeting`). Every other kind must be off until the person switches it on.

Reason: Too many pushes make people switch push off entirely.

Test: `backend/tests/unit/modules/notifications/test_push_pure.py`,
`backend/tests/integration/modules/notifications/test_push_api.py`.
