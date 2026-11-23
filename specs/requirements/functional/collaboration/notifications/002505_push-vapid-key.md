---
id: "002505"
title: The platform makes its own push key
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

# The platform makes its own push key

The platform must make its VAPID key pair itself at the first need and store it in the database.
It must never replace an existing key pair. The private key must never leave the backend.

Reason: No deploy change is needed, and a restore keeps the devices subscribed, because the key
comes back with the database.

Test: `backend/tests/integration/modules/notifications/test_push_api.py`.
