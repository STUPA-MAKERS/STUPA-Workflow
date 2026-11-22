---
id: "002406"
title: No :has() at the page root
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-22
tests:
  - "frontend/vendor/ui-kit/src/styles/root-has.spec.ts:withoutComments"
  - "frontend/vendor/ui-kit/src/lib/sticky-bar/stuck-heads.spec.ts:StuckHeads"
  - "frontend/vendor/ui-kit/src/lib/file-viewer/file-viewer.component.spec.ts:FileViewerComponent"
implementation:
  - frontend/vendor/ui-kit/src/lib/sticky-bar/stuck-heads.ts
  - frontend/vendor/ui-kit/src/lib/sticky-bar/sticky-bar.component.ts
  - frontend/vendor/ui-kit/src/lib/list-group/list-group.component.ts
  - frontend/vendor/ui-kit/src/lib/tab-pager/tab-pager.component.ts
  - frontend/vendor/ui-kit/src/lib/list-detail/list-detail-bar.component.ts
  - frontend/vendor/ui-kit/src/styles/base.scss
  - frontend/vendor/ui-kit/src/lib/file-viewer/file-viewer.component.ts
scope:
  - frontend/vendor/ui-kit
---

# No :has() at the page root

A selector of the kit must not use `:has()` on `body`, `html` or `:root`. A component that
styles the page from the state of another component must learn that state through a class or
an attribute of its own: the list groups and the tab pager report a stuck head to
`StuckHeads`, and the sticky bar and the bar of a detail set `stb--covered` and
`ld__bar--covered`. The file viewer sets `data-file-viewer` on `<html>` while it is open, and
the blur of the page reads that attribute.

Reason: With a `:has()` at the page root, a class that changes or an element that the page
inserts anywhere can make the browser style every element of the page again. On Anträge the
first group head that sticks cost 13 ms on a desktop CPU, and the press ripple that a touch
inserts into a row cost 7.8 ms, so a Pixel 7 with a 4× slower CPU lost 40 to 120 ms at the
start of every touch and again when the ripple faded. These are the frames in which the FAB
fold starts, so the fold stalled whenever the finger landed on a row.

Test: The contract test of the kit reads every stylesheet without its comments and fails on
a `:has()` at the page root. The test of `StuckHeads` checks the count of stuck heads, and
the test of the file viewer checks `data-file-viewer` while it is open and after it closes.
