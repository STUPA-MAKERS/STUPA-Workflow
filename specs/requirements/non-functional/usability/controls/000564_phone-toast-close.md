---
id: "000564"
title: A toast closes by a swipe, by its close button or by its time
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "frontend/src/app/shared/ui/load-error/load-error.component.spec.ts:LoadErrorComponent"
implementation:
  - frontend/src/app/shared/ui/load-error/load-error.component.ts
  - frontend/vendor/ui-kit/src/lib/toast/toast.component.ts
  - frontend/vendor/ui-kit/src/lib/toast/toast.component.scss
scope:
  - frontend/vendor/ui-kit
  - frontend/src/app/
---

# A toast closes by a swipe, by its close button or by its time

On a phone, a toast must not show a close button. A swipe up on the toast must close it. On
a screen wider than a phone, each toast must have a close button. A toast must close by
itself when its time runs out.

The toast of a load error (000576) must not close by its time. It must close when the person
presses the retry action, swipes it away on a phone or presses its close button on a wide
screen. It must also close when the content loads.

Reason: The close button took room from the message of a phone toast, and a mouse cannot
swipe. The load error toast holds the only retry of the page: a toast that closes by its
time leaves an empty page with no way to load it again.

Test: A unit test opens a load error toast, advances the clock past the toast time and
expects the toast to stay.
