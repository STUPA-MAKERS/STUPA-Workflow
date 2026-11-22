---
id: "002406"
title: No :has() at the page root reads a state that a scroll changes
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-22
tests:
  - "frontend/vendor/ui-kit/src/styles/root-has.spec.ts:scrollStates"
  - "frontend/vendor/ui-kit/src/lib/sticky-bar/stuck-heads.spec.ts:StuckHeads"
implementation:
  - frontend/vendor/ui-kit/src/lib/sticky-bar/stuck-heads.ts
  - frontend/vendor/ui-kit/src/lib/sticky-bar/sticky-bar.component.ts
  - frontend/vendor/ui-kit/src/lib/list-group/list-group.component.ts
  - frontend/vendor/ui-kit/src/lib/tab-pager/tab-pager.component.ts
  - frontend/vendor/ui-kit/src/lib/list-detail/list-detail-bar.component.ts
  - frontend/vendor/ui-kit/src/styles/base.scss
scope:
  - frontend/vendor/ui-kit
---

# No :has() at the page root reads a state that a scroll changes

A selector of the kit must not read a class that a component sets while the page scrolls (a stuck head,
a bar under content, a folded FAB) through `:has()` on `body`, `html` or `:root`. The component
that the rule styles must learn the state through a class of its own. In the kit, the list
groups and the tab pager report a stuck head to `StuckHeads`, and the sticky bar and the bar of
a detail set `stb--covered` and `ld__bar--covered`.

Reason: A class that changes inside `body:has()` makes the browser style every element of the
page again. On Anträge the first group head that sticks cost 13 ms on a desktop CPU and about
50 to 80 ms on a Pixel 7 with a 4× slower CPU, in the first frame of each scroll down. The fold
of the FAB starts in that frame, so it lost its first frames.

Test: The contract test of the kit reads every stylesheet and fails on a `:has()` at the page
root that names a scroll state class. The test of `StuckHeads` checks the count of stuck heads.
