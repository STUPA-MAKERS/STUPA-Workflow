---
id: "000515"
title: Each drag has an alternative without a drag
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-08
tests:
  - "frontend/src/app/pages/admin/flow/flow-editor.component.spec.ts:FlowEditorDragAlternative"
implementation:
  - frontend/src/app/pages/admin/flow/flow-editor.component.ts
  - frontend/src/app/pages/admin/flow/flow-editor.component.html
  - frontend/src/app/features/meetings/agenda-pane/agenda-pane.component.ts
  - frontend/src/app/pages/admin/forms/form-editor.component.ts
  - frontend/src/app/pages/todos/board-settings/todo-board-settings.component.ts
  - frontend/src/app/features/todos/move-sheet
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# Each drag has an alternative without a drag

A drag on a board, in a TOP list or in the flow editor must have an alternative without a
drag, for example the Verschieben sheet or arrow buttons.

Reason: WCAG 2.5.7.
