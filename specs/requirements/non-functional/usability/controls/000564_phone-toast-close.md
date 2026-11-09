---
id: "000564"
title: A phone toast closes by a swipe or by its time
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-09
implementation:
  - frontend/vendor/ui-kit/src/lib/toast/toast.component.ts
  - frontend/vendor/ui-kit/src/lib/toast/toast.component.scss
scope:
  - frontend/vendor/ui-kit
---

# A phone toast closes by a swipe or by its time

On a phone, a toast must not show a close button. A swipe up on the toast must close it. A
toast must close by itself when its time runs out.

Reason: The close button took room from the message. The time-out is the way to close a
toast without a gesture.
