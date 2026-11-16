---
id: "001074"
title: One search field picks Gremien and persons
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "frontend/src/app/features/gremien/gremium-person-picker/gremium-person-picker.component.spec.ts:GremiumPersonPickerComponent"
  - "frontend/src/app/features/calendar/appointment-dialog/appointment-dialog.component.spec.ts:AppointmentDialogComponent"
  - "backend/tests/integration/modules/todos/test_todos_free_boards.py:test_the_picker_finds_gremien_and_persons"
implementation:
  - frontend/src/app/features/gremien/gremium-person-picker/gremium-person-picker.component.ts
  - frontend/src/app/features/calendar/appointment-dialog/appointment-dialog.component.ts
  - frontend/src/app/pages/todos/board-entries/todo-board-entries.component.ts
  - backend/app/modules/todos/service.py
  - backend/app/modules/site_config/square_logos.py
scope:
  - frontend/src/app/features/todos
  - frontend/src/app/features/calendar
  - frontend/src/app/shared
---

# One search field picks Gremien and persons

The choice of Gremien and persons must be one search field. A search must find Gremien by name
and persons by name. Each hit must be a row with an image and the name: a person shows the
avatar, a Gremium shows its logo (`app-gremium-logo`, the initials without a logo). The hits must
open in a popover over the content, so the dialog does not grow. The chosen Gremien and persons
must show as chips above the field and must be removable. There must be no separate button
`+ Gremium`. The member entries of a free board and the invitations of a Termin must use this
field.

Reason: One field for both is faster, and a list that grows inside a dialog pushes its buttons
out of view.

Test: A frontend test types a name, finds a Gremium and a person in the popover, picks both and
finds two chips, and the dialog height does not change.
