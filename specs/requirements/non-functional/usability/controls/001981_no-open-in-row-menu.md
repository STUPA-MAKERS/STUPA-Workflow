---
id: "001981"
title: The ⋮ of a list row has no "Öffnen"
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
tests:
  - "frontend/src/app/pages/applications/row-transitions-menu/row-transitions-menu.component.spec.ts:RowTransitionsMenuComponent"
  - "frontend/src/app/pages/applications/applications-list.component.spec.ts:ApplicationsListComponent"
implementation:
  - frontend/src/app/pages/applications/row-transitions-menu
  - frontend/src/app/pages/applications/applications-list.component.html
scope:
  - frontend/src/app/
---

# The ⋮ of a list row has no "Öffnen"

The ⋮ menu of a list row must not contain an item that opens the row, such as "Öffnen". A
press on the row opens it. A list row without a press action may keep such an item. An item
that opens a different thing, for example "Datei öffnen" of an invoice row, stays.

When the menu of a row would hold no item for the reader at all, the row must show no ⋮.

Reason: The press on the row and the item did the same thing. The item made the menu longer
without a new action.

Test: A unit test of the Anträge row menu checks that the menu has no "Öffnen", and a unit
test of the Anträge list checks that a reader without an action right sees no ⋮.
Screenshots of the open menu in the light and the dark theme and in the very high contrast
mode.
