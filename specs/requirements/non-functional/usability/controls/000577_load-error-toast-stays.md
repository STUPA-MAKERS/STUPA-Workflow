---
id: "000577"
title: A load error toast stays until it is closed
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-09
tests:
  - "frontend/src/app/shared/ui/load-error/load-error.component.spec.ts:LoadErrorComponent"
implementation:
  - frontend/src/app/shared/ui/load-error/load-error.component.ts
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# A load error toast stays until it is closed

The toast of a load error (000576) must not close by its time. It must close when the person
presses the retry action, swipes it away on a phone (000564) or presses its close button on
a wide screen (000568). It must also close when the content loads.

Reason: The toast holds the only retry of the page. A toast that closes by its time leaves an
empty page with no way to load it again.

Test: A unit test opens a load error toast, advances the clock past the toast time and
expects the toast to stay.
