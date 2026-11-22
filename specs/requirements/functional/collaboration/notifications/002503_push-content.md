---
id: "002503"
title: A push shows a title and one short line
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

# A push shows a title and one short line

A push must show the name of its kind as the title (for example "Neue Erwähnung") and the
subject of the mail of the same event as the one short line. Tapping the push must open the
element of the event, the same link as the button of the mail. The push must be in the language
of the mail.

Reason: The person decides from the lock screen whether to open it.

Test: `backend/tests/unit/modules/notifications/test_push_pure.py`,
`backend/tests/integration/modules/notifications/test_push_send.py`.
