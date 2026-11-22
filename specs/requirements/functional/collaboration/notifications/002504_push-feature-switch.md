---
id: "002504"
title: Push has a feature switch
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-22
implementation:
  - backend/app/modules/notifications
  - frontend/src/app/pages/account
scope:
  - backend/app/modules/notifications
  - backend/worker/push.py
  - frontend/src/app/core/pwa
  - frontend/src/app/pages/account
---

# Push has a feature switch

Push must have a switch under /admin/features (`push`). While it is off, the platform must send
no push, the account page must show no push controls, and the push routes must answer 404.

Reason: Admins introduce push step by step and can stop it at once.

Test: `backend/tests/integration/modules/features/test_features_api.py`.
