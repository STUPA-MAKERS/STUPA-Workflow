---
id: "000566"
title: A phone toast action is an icon button
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-09
implementation:
  - frontend/vendor/ui-kit/src/lib/toast/toast.component.html
  - frontend/vendor/ui-kit/src/lib/toast/toast.component.scss
  - frontend/src/app/pages/applications/applications-list.component.ts
  - frontend/src/app/pages/invoices/invoices.component.ts
scope:
  - frontend/vendor/ui-kit
  - frontend/src/app/
---

# A phone toast action is an icon button

On a phone, the action of a toast (for example "Rückgängig") must be a round icon button of
40px at the end of the card. Its label must be the accessible name and the tooltip of the
button. A toast without an action must keep an empty space of 40px at the end, so that the
message stays centred.

Reason: A text button made the card uneven and took room from the message.
