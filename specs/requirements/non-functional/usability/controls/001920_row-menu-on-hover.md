---
id: "001920"
title: The ⋮ of a list row shows only for the row in use
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
tests:
  - "frontend/vendor/ui-kit/src/lib/list-item/list-item.component.spec.ts:ListItemComponent"
implementation:
  - frontend/vendor/ui-kit/src/lib/list-item
  - frontend/vendor/ui-kit/src/styles/_list-pane.scss
  - frontend/src/app/pages/applications
  - frontend/src/app/pages/expenses
  - frontend/src/app/pages/invoices
  - frontend/src/app/pages/admin
scope:
  - frontend/vendor/ui-kit/src/lib/list-item
  - frontend/src/app/
---

# The ⋮ of a list row shows only for the row in use

On a device with hover, the ⋮ menu of a list row must show only while the pointer is on the
row, while a control of the row has the visible keyboard focus, or while its menu is open. At
rest the ⋮ must take no width, and the title, the sub line and the trail of the row must use
the full width of the row. On a touch screen the ⋮ must always show. The ⋮ sits in the
`[menu]` slot of the ui-kit list item, so every list gets the same behaviour. In a list in one
column, the arrow at the end of a row must show at rest and must give way to the ⋮.

The TOPs beside the protocol keep their split boxes (001443).

Reason: The ⋮ of every row at once was noisy, and its empty place cut the titles of the rows
without need.

Test: A unit test of the list item checks the slot and the hover rules. Screenshots of the
Anträge, Buchungen and Rechnungen on a wide screen, at rest, with hover, with the keyboard
focus and with an open menu, in the light and the dark theme and in the very high contrast
mode.
