---
id: "003125"
title: The flow layout runs in a web worker
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-28
implementation:
  - frontend/src/app/pages/admin/flow/flow-elk.ts
scope:
  - frontend/src/app/pages/admin/flow
---

# The flow layout runs in a web worker

The automatic layout of the flow canvas (ELK) must run in a web worker, not on the main thread.
A layout must not block input or drawing. While a new layout runs after an edit, the canvas
must keep the last layout and must not jump to the stored places.

Reason: ELK on the main thread froze the page for 300 to 600 ms at the load and at each edit of
the structure, measured with a flow of 18 states and 55 transitions.

Test: A unit test expects the layouter to post the graph to a worker. An e2e test adds a state
and expects no long task over 100 ms.
