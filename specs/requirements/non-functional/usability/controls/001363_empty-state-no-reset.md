---
id: "001363"
title: An empty state has no reset button
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
implementation:
  - frontend/src/app/pages/invoices/invoices.component.html
  - frontend/src/app/pages/expenses/expenses.component.html
  - frontend/src/app/features/public-protocols/public-protocols.component.html
  - frontend/src/app/features/public-protocols/public-decisions.component.html
  - frontend/src/app/features/meetings/agenda-item-dialog/agenda-item-dialog.component.html
scope:
  - frontend/src/app/
---

# An empty state has no reset button

An empty state must not show a button that resets the filters or clears the search. The reset
must be in the filter row of the list, where it shows while a filter is set, or the clear button
of the search field.

An empty state may show one way to create something below its hint, such as "Als Freitext
anlegen" or "Info bearbeiten" (000205).

Reason: The empty state is a quiet hint under the face (001360). The filter row already holds
the filters, so the reset belongs beside them and is there whether the list is empty or not.

Test: The unit tests of the lists click the reset in the filter row or the clear button of the
search field.
