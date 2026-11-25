---
id: "003040"
title: The page Status & Phasen uses the editor of the plan steps
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-25
implementation:
  - frontend/src/app/pages/admin/statuses/statuses.component.html
scope:
  - frontend/src/app/pages/admin
  - backend/app/modules/statuses
---

# The page Status & Phasen uses the editor of the plan steps

The page `Status & Phasen` must show one section per kind of element (`Bestellungen`,
`Veranstaltungen`). Each section must edit its statuses with the same components as the steps
of a Haushaltsplan under Verwaltung > Budgets: a numbered list, per row the name, the buttons up
and down, the delete button and the selects of the row (phase, color, and for a Bestellung the
date of 003037), and the button `+ Status` under the list. The order of the list is the position
of the statuses. A status must show in the lists and details of its element in the same way as
the state of a Haushaltsplan version. The storage must follow the schema of the plan steps: one
row per status with the list, the position and its values.

Reason: An admin who knows the steps of a plan knows this page at once. One editor and one
display keep the platform the same and need no new kit component.

Test: A frontend unit test adds a status, moves it up and reads the request with the new
positions.
