---
id: "001790"
title: A pick dialog lists its choices as the select sheet does
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
tests:
  - "frontend/src/app/features/meetings/agenda-item-dialog/agenda-item-dialog.component.spec.ts:AgendaItemDialogComponent"
  - "frontend/src/app/features/todos/pick-dialog/todo-pick-dialog.component.spec.ts:TodoPickDialogComponent"
implementation:
  - frontend/src/app/shared/ui/_pick-rows.scss
  - frontend/src/app/features/meetings/agenda-item-dialog/agenda-item-dialog.component.html
  - frontend/src/app/features/meetings/agenda-item-dialog/agenda-item-dialog.component.scss
  - frontend/src/app/features/todos/pick-dialog/todo-pick-dialog.component.html
  - frontend/src/app/features/todos/pick-dialog/todo-pick-dialog.component.scss
scope:
  - frontend/src/app/features/meetings/agenda-item-dialog
  - frontend/src/app/features/todos/pick-dialog
---

# A pick dialog lists its choices as the select sheet does

The choice lists of "TOP hinzufügen" (Anträge, Haushaltspläne, To-Dos) and of "Auf
Tagesordnung setzen" must show the rows of the select sheet (001380), with the subtitle under
the title: a row group of tiles on surface 3, 2px apart, with round outer corners only. A row
must have no radio circle. The chosen row must show its title in semibold and a check mark
after its text.

Reason: The rows had a radio circle and no surface, so the list did not read as the other
choice lists of the app, and on a list of To-Dos the circle looked like the "erledigt" mark of
a card.

Test: the specs of both dialogs check the radio rows, the row group and the check mark of the
chosen row.
