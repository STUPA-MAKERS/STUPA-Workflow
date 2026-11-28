---
id: "003131"
title: The flow inspector opens over the canvas
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-28
tests:
  - "frontend/src/app/pages/admin/flow/flow-editor.component.spec.ts:FlowEditorComponent.sheetOpen"
implementation:
  - frontend/src/app/pages/admin/flow/flow-editor.component.html
scope:
  - frontend/src/app/pages/admin/flow
---

# The flow inspector opens over the canvas

In the detail pane, the canvas of the flow editor must use the full width of the pane. The
inspector must open as a sheet over the right side of the canvas only when a state, a
transition or a group is selected, or when "Versionen" is on. The sheet must have a close
button. Escape and a click on the empty canvas must close it too. The canvas must keep the
selected item visible beside the sheet. On the phone, the sheet opens from the bottom.

Reason: The pane is too narrow for the canvas and a fixed inspector side by side.

Test: A unit test selects a state and expects the sheet, then presses Escape and expects no
sheet.
