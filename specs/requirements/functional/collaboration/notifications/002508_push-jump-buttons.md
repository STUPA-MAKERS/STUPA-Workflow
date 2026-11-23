---
id: "002508"
title: A push can carry jump buttons
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-23
implementation:
  - backend/app/modules/notifications
  - backend/app/modules/notifications/push_service.py
scope:
  - backend/app/modules/notifications
  - frontend/src/app/core/pwa
---

# A push can carry jump buttons

A push may carry at most two buttons. A jump button must open one place of the platform, for
example "Zur Abstimmung" on a started poll. A device that shows no buttons (iOS, Firefox) must
open the element of the push on a tap, so every button action must also be reachable in the app.

Reason: Android and desktop Chrome show at most two buttons; iOS and Firefox show none.

Test: `backend/tests/unit/modules/notifications/test_push_pure.py`.
