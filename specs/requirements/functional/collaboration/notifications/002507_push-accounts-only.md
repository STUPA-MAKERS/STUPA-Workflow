---
id: "002507"
title: Only accounts get push
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

# Only accounts get push

Push must be available only to principals with an account. An applicant with a magic link must
get no push and no push controls.

Reason: Applicants rarely install the PWA, and iOS has no push without installation.

Test: `backend/tests/integration/modules/notifications/test_push_api.py`.
