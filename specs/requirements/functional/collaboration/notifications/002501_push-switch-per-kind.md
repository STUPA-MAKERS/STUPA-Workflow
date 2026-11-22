---
id: "002501"
title: Push has its own switch per kind
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

# Push has its own switch per kind

Each mail kind of Konto → Benachrichtigungen must have its own push switch, in a group "Per
Push" below the mail switches. The push switch and the mail switch must not change each other. A
push must go only to a person who would get the mail of the same event if the mail switch were
on, so the rule "only who can act" (F/collaboration/notifications/000151) holds for push too.

Reason: Push suits urgent events, mail suits the record; a person often wants one without the
other.

Test: `backend/tests/integration/modules/notifications/test_push_send.py`,
`backend/tests/integration/modules/notifications/test_push_api.py`.
