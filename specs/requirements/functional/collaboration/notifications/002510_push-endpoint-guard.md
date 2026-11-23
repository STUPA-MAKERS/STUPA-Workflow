---
id: "002510"
title: A push goes only to a known push service
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
implementation:
  - backend/app/modules/notifications/push_service.py
  - backend/worker/push.py
scope:
  - backend/app/modules/notifications
  - backend/worker/push.py
---

# A push goes only to a known push service

The platform must accept a device subscription only with an `https` endpoint on a host of a
known push service (Google, Apple, Mozilla, Microsoft). The worker must send each push through
the SSRF guard and must not follow a redirect.

Reason: The browser hands over the endpoint, so a forged one would make the server call any
address.

Test: `backend/tests/unit/modules/notifications/test_push_pure.py`,
`backend/tests/integration/modules/notifications/test_push_send.py`.
