---
id: "003040"
title: The pages Bestellphasen and Veranstaltungsphasen use the editor of the plan steps
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-25
implementation:
  - frontend/src/app/pages/admin/statuses/statuses.component.html
  - frontend/vendor/ui-kit/src/lib/step-list/step-list.component.ts
scope:
  - frontend/src/app/pages/admin
  - backend/app/modules/statuses
---

# The pages Bestellphasen and Veranstaltungsphasen use the editor of the plan steps

Each status list must have its own page under Verwaltung (003035): `Bestellphasen` for the
list of the Bestellungen, shown only while the feature of the Bestellungen is on, and
`Veranstaltungsphasen` for the list of the Events. Each page must edit its list with the layout
of the steps of a Haushaltsplan under Verwaltung > Budgets: a numbered list, per row the name,
the buttons up and down, the delete button and the selects of the row (phase, color, and for a
Bestellung the date of 003037), and the add button under the list. The numbered list must be the
kit component `app-step-list`, so the pages have no styles of their own (002213). The order of
the list is the position of the statuses. A status must show in the lists and details of its
element in the same way as the state of a Haushaltsplan version. The storage must follow the
schema of the plan steps: one row per status with the list, the position and its values.

Reason: An admin who knows the steps of a plan knows these pages at once. One page per list
says on its name which element it configures. One editor and one display keep the platform the
same.

Test: A frontend unit test adds a status on the page Bestellphasen, moves it up and reads the
request with the new positions, and reads that the page Veranstaltungsphasen sends only the list
of the Events.
