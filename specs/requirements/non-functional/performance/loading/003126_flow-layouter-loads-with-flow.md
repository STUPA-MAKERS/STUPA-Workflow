---
id: "003126"
title: The flow editor loads the layouter while it reads the flow
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-28
implementation:
  - frontend/src/app/pages/admin/flow/flow-editor.component.ts
scope:
  - frontend/src/app/pages/admin/flow
---

# The flow editor loads the layouter while it reads the flow

The flow editor must start to load the layouter (the ELK worker) at the same time as the read of
the flow, not after the read answers. The skeleton of the canvas must show until the first
layout answers, and the canvas must then show at once with its final places.

Reason: The two loads ran one after the other, and the wait was their sum.

Test: A unit test expects the layouter load to start before the read of the flow answers.
