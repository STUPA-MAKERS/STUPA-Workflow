---
id: "002905"
title: A dialog with a search or a list has a tight body
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
implementation:
  - frontend/vendor/ui-kit/src/lib/dialog/dialog.component.scss
  - frontend/src/app/features/meetings/delegation-dialog/delegation-dialog.component.html
  - frontend/src/app/features/meetings/lead-substitute-dialog/lead-substitute-dialog.component.html
  - frontend/src/app/features/meetings/agenda-item-dialog/agenda-item-dialog.component.html
  - frontend/src/app/features/todos/pick-dialog/todo-pick-dialog.component.html
  - frontend/src/app/features/apply/observers-dialog/observers-dialog.component.html
  - frontend/src/app/pages/applications/agenda-dialog/agenda-dialog.component.html
  - frontend/src/app/pages/todos/archived-boards/todo-archived-boards.component.html
  - frontend/src/app/pages/admin/committees/substitute-pool.component.html
  - frontend/src/app/pages/admin/users/user-merge/user-merge.component.html
scope:
  - frontend/src/app/features
---

# A dialog with a search or a list has a tight body

A dialog whose body starts with a search or a list must use the tight body of the kit dialog (`body="tight"`): no
space above and below the body instead of 16px. The search sits directly under the head and the
list ends directly above the footer. This applies to "Vertretung einrichten", "Vertretung
eintragen", "TOP hinzufügen", "Auf Tagesordnung setzen" (to-do and Antrag), "Beobachter",
"Archivierte Boards", "Stellvertretung hinzufügen" and the pick step of "Konten zusammenführen".
A dialog that is a form (fields, text) must keep the normal body. A list in these dialogs has no
scroll fade: it cuts hard at its rounded corners.

Reason: Around a search or a list the normal space looked too large (Frederik, 2026-11-24:
"überall so").

Test: Screenshot review.
