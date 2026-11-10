---
id: "000546"
title: The detail shows Vorgänger and Folgeanträge
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-10
implementation:
  - frontend/src/app/pages/applications/applications-detail.component.ts
  - frontend/src/app/features/todos/linked-list/todo-linked-list.component.ts
scope:
  - backend/app/modules/applications
  - frontend/src/app/pages/applications
---

# The detail shows Vorgänger and Folgeanträge

The detail of an Antrag must show its Vorgänger and its Folgeanträge as rows in the section
"Verknüpft". Each row must open the linked Antrag. The Vorgänger must also show as a row of
the details, with the button that links or changes it. The Folgeanträge must show only in
"Verknüpft". A row must show only when the reader can open the linked Antrag. The applicant
view must follow the same rule.

Reason: The reader sees the history of a recurring Antrag in one place, next to the other
linked objects. An Antrag can have many Folgeanträge, so a single row of the details does not
fit them. A hidden row keeps the title of an Antrag away from a reader without access.

Test: Unit tests of the detail read: a link to an Antrag outside the read scope is not in the
result. A frontend test checks both rows and the navigation.
