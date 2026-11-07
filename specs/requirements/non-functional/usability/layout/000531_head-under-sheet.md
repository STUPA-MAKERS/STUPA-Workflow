---
id: "000531"
title: The page head stays in view under an open sheet
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-07
tests:
  - "frontend/vendor/ui-kit/src/lib/focus/focus-trap.spec.ts:lockBodyScroll"
implementation:
  - frontend/vendor/ui-kit/src/lib/focus/focus-trap.ts
  - frontend/vendor/ui-kit/src/lib/file-viewer
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# The page head stays in view under an open sheet

While a sheet, a dialog or the file viewer is open, the page behind it must keep its look. The
head of the page (title, back, actions, tabs) must stay where it was, under the scrim. The page
must not jump and must not show content under the status bar.

Reason: The open sheet locks the scroll of the page. A lock with `overflow: hidden` on the body
makes the body a scroll container, because the phone sets `overflow-x: clip` on the root and
the root then no longer passes the body value to the viewport. A sticky head then sticks to
the body, which does not scroll, and moves out of view. The lock must therefore stop the scroll
on the root element, which always passes its value to the viewport.

Test: `frontend/vendor/ui-kit/src/lib/focus/focus-trap.spec.ts` (the lock sets the root, not
the body) and a check of the phone screenshots with an open sheet.
