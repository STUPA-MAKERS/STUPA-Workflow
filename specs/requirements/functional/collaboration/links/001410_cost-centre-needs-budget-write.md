---
id: "001410"
title: A cost centre link needs a budget write right
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-20
implementation:
  - backend/app/modules/todos/link_rights.py
  - backend/app/modules/todos/link_service.py
  - frontend/src/app/features/todos/link-picker/todo-link-picker.component.ts
scope:
  - backend/app/modules/todos
  - frontend/src/app/features/todos
---

# A cost centre link needs a budget write right

A person must be able to add or remove a link with a cost centre end only when the person holds
`budget.book` or `budget.structure`. This rule must apply in addition to spec 001404, whatever
the other end is. The link search must not show a cost centre to a person without one of these
rights, and the picker must not show the kind "Haushalt" to that person. A linked cost centre
must show without the remove button to that person.

Reason: A link to a cost centre changes how the budget is read, so only a person who may write
the budget may add or remove it.

Test: A backend unit test refuses a cost centre link for a person with the change right on the
other end but without a budget write right, and accepts it with `budget.book`. A test of the link
search leaves out the cost centres for that person. A frontend test hides the kind "Haushalt"
without a budget write right.
