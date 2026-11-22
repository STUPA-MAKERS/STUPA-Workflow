---
id: "002500"
title: A person switches on push for one device
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

# A person switches on push for one device

A person with an account must be able to switch on push notifications for the device they use,
under Konto → Benachrichtigungen. The browser must ask for the permission only after the person
taps the switch. Each device must be one subscription, and the page must list the devices of the
person, each with a way to remove it.

Reason: iOS asks for the permission only after a tap, and a person has more than one device.

Test: `backend/tests/integration/modules/notifications/test_push_api.py`,
`frontend/src/app/pages/account/notifications.component.spec.ts`.
