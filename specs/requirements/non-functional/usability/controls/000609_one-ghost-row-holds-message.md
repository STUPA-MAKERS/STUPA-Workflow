---
id: "000609"
title: One ghost row holds the message and shows no bars
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-10
tests:
  - "frontend/vendor/ui-kit/src/lib/empty-state/empty-state.component.spec.ts:EmptyStateComponent"
implementation:
  - frontend/vendor/ui-kit/src/lib/empty-state/empty-state.component.html
  - frontend/vendor/ui-kit/src/lib/empty-state/empty-state.component.scss
scope:
  - frontend/vendor/ui-kit/src/lib/empty-state
---

# One ghost row holds the message and shows no bars

When `app-empty-state` shows one ghost row (`rows="1"`, 000597), the row must be as high as the
message, and the message must sit inside the row. The row must show no bars, no chips and no
lead shapes. It is one faint surface in the geometry of a list row, with the heading and the
body in its centre.

Empty states with two or more ghost rows do not change. Their rows keep the bars, and the
message stays on the scrim over the rows.

Reason: One row is lower than the heading and the body. The message then overlaps the row and
hangs out below it, and the bars on the left and right look like a list that is still loading.

Test: A unit test renders the empty state with `rows="1"` and expects the one-row class and no
bar elements. A second test with `rows="3"` expects the bars.
