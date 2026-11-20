---
id: "002161"
title: Layout reads wait for the render and come before the writes of a frame
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-20
tests:
  - "frontend/vendor/ui-kit/src/lib/util/frame-read.spec.ts:frameRead"
  - "frontend/vendor/ui-kit/src/lib/scroll-fade/scroll-fade.directive.spec.ts:ScrollFadeDirective"
implementation:
  - frontend/vendor/ui-kit/src/lib/util/frame-read.ts
  - frontend/vendor/ui-kit/src/lib/scroll-fade/scroll-fade.directive.ts
  - frontend/vendor/ui-kit/src/lib/focus/route-focus.ts
  - frontend/vendor/ui-kit/src/lib/signals/element-size.ts
  - frontend/vendor/ui-kit/src/lib/sticky-bar/sticky-bar.component.ts
  - frontend/vendor/ui-kit/src/lib/list-detail/list-detail-bar.component.ts
  - frontend/vendor/ui-kit/src/lib/truncated/truncated.directive.ts
  - frontend/vendor/ui-kit/src/lib/page-header/page-header.component.ts
scope:
  - frontend/vendor/ui-kit
  - frontend/src/app
---

# Layout reads wait for the render and come before the writes of a frame

A component must not read the layout (`getBoundingClientRect`, `getComputedStyle`, `offset*`,
`scroll*`, `client*`) while Angular renders. It must read in the read phase of
`afterNextRender`, `afterEveryRender` or `afterRenderEffect`, in a `ResizeObserver`, or in the
shared frame queue of the kit (`frameRead`), which runs all reads of a frame before all of its
writes. A component must not look for an element in each frame: the focus after a navigation
looks after each render and every 250 ms.

Reason: A read after a write makes the browser lay out the page at once. On a page change the
fades, the focus, the size signals, the sticky bar and the truncated texts each read after a
write, so a phone laid out the new page up to seven times before its first frame. The section
switch to Anträge froze for 390 ms on a Pixel 7 with a 4× slower CPU, and for 271 ms after the
change.

Test: The tests of the frame queue check that the reads of a frame run before its writes and
that a cancelled read does not run. The test of the fade checks that rows that come or go
measure once in the next frame, not in the render.
