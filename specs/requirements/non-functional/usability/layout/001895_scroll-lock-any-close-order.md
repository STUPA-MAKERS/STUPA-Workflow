---
id: "001895"
title: The page scrolls again when the last overlay closes, in any order
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
tests:
  - "frontend/vendor/ui-kit/src/lib/focus/focus-trap.spec.ts:lockBodyScroll"
implementation:
  - frontend/vendor/ui-kit/src/lib/focus/focus-trap.ts
  - frontend/vendor/ui-kit/src/lib/side-sheet
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# The page scrolls again when the last overlay closes, in any order

While a sheet, a dialog or the file viewer is open, the page behind it does not scroll
(000531). When the last of them closes, the page must scroll again, in whatever order they
closed. Every lock of the page is counted, and only the release of the last lock gives the page
its old scroll back.

Reason: Each overlay restored the scroll value that it found. A sheet that closed after the
dialog it had opened restored the lock of the dialog, and the whole app stayed unscrollable on
the phone until a restart.

Test: A unit test opens two locks, releases them in the wrong order and expects the page to stay
locked until the last release, then to get its old value back.
