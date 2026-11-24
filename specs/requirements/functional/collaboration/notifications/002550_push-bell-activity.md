---
id: "002550"
title: A bell in the head of Aktivität asks for push and opens the settings
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
implementation:
  - frontend/src/app/pages/activity
scope:
  - frontend/src/app/pages/activity
  - frontend/src/app/core/pwa
---

# A bell in the head of Aktivität asks for push and opens the settings

The head of the page Aktivität must show a bell button as its one action, at the top right on
every width. The page must not show "Antrag stellen", neither in the head nor as the floating
button. A tap on the bell must first switch on push for this device when the feature push is on,
the device can take push and has no subscription yet; the browser then asks for the permission.
After that, and in every other case at once, the tap must open Konto → Benachrichtigungen. A
refused or failed permission must not stop the opening of the settings.

Reason: Aktivität is the start page, and the push switch is deep in the account menu. A new
Antrag starts from the page Anträge.

Test: `frontend/src/app/pages/activity/activity.component.spec.ts`.
