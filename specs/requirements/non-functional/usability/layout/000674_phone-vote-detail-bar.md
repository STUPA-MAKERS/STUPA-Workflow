---
id: "000674"
title: The phone vote detail uses the bar of the other details
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-11
implementation:
  - frontend/src/app/features/voting/phone-header
  - frontend/src/app/features/voting/vote-cast.component.ts
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# The phone vote detail uses the bar of the other details

On the phone the vote detail must use the detail bar of the other detail views: the back
arrow, the actions and, after a scroll, the title. The bar must not show the word
"Abstimmung" and the meeting line. The meeting and the TOP stay in the status line below the
title.

Reason: The vote detail is the only detail with its own header. Every other detail shows the
context below the title.

Test: A unit test of the vote detail at phone width expects the detail bar of the kit and no
own header.
