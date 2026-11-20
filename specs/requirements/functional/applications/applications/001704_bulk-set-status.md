---
id: "001704"
title: The bulk action of the Antrag list sets a status and skips the Anträge that cannot take it
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
tests:
  - "backend/tests/unit/modules/flow/test_bulk_unit.py:test_an_unreadable_antrag_reaches_no_target"
  - "backend/tests/integration/modules/applications/test_bulk_actions.py:test_a_bulk_transition_runs_per_antrag"
  - "frontend/src/app/pages/applications/bulk-dialog/bulk-dialog.component.spec.ts:BulkDialogComponent"
implementation:
  - backend/app/modules/flow/bulk.py
  - frontend/src/app/pages/applications/bulk-dialog/bulk-dialog.component.ts
scope:
  - backend/app/modules/flow
  - frontend/src/app/pages/applications
---

# The bulk action of the Antrag list sets a status and skips the Anträge that cannot take it

The bulk action of the selection bar of the Anträge is `Status setzen` (`Set status`), with the
icon of `Status setzen` of one Antrag. It replaces `Übergang auslösen`.

The dialog must offer every target status that at least one selected Antrag reaches by a manual
transition that the person may fire. The label is the name of the target status, and the
statuses are rows of the select sheet (001380). When the person picks a status that not every
selected Antrag reaches, the dialog must name the Anträge that it skips. It shows no count per
status.

The workflow rules stay: the server sets the status only through the transition of each Antrag,
and it checks the read right, the transition and its guard of each Antrag again. An Antrag
without a transition into the chosen status is skipped, and its result line says
`Übersprungen: Status nicht erlaubt` (001703). An Antrag that the person cannot read reaches no
status.

Reason: Frederik wants a collective `Status setzen` in place of `Übergang auslösen`. A selection
of Anträge in different states had no common transition, so the dialog offered nothing.

Test: A backend integration test asks for the options after one Antrag moved, and the option
names only the two Anträge that still reach the status.
