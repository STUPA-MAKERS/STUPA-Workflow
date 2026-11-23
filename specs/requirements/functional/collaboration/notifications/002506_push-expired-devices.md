---
id: "002506"
title: An expired device subscription is removed
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

# An expired device subscription is removed

When the push service answers 404 or 410 for a subscription, the worker must delete that
subscription. A send must never retry for such an answer.

Reason: A browser drops a subscription when the person removes the app or the permission.

Test: `backend/tests/integration/modules/notifications/test_push_send.py`.
