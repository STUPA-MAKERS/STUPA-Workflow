---
id: "001791"
title: The empty state of a pick dialog is centred in the list area
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-20
implementation:
  - frontend/src/app/features/meetings/agenda-item-dialog/agenda-item-dialog.component.scss
  - frontend/src/app/features/todos/pick-dialog/todo-pick-dialog.component.scss
scope:
  - frontend/src/app/features/meetings/agenda-item-dialog
  - frontend/src/app/features/todos/pick-dialog
---

# The empty state of a pick dialog is centred in the list area

When the list of a pick dialog (001790) has no row, its empty state must sit in the vertical
middle of the free height of the list area, not at its top. This applies to "TOP hinzufügen"
(Anträge, Haushaltspläne, To-Dos) and to "Auf Tagesordnung setzen".

Reason: The list area has a fixed height so that the dialog keeps its height. An empty state at
the top left a large empty band under it.
