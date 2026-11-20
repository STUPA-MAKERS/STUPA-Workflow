---
id: "001810"
title: A long press selects in every list with a multiple selection
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-20
tests:
  - "frontend/src/app/pages/applications/applications-list.component.spec.ts:ApplicationsListComponent"
  - "frontend/src/app/pages/applications/attachments-panel.component.spec.ts:AttachmentsPanelComponent"
  - "frontend/src/app/pages/expenses/expenses.component.spec.ts:ExpensesComponent"
implementation:
  - frontend/vendor/ui-kit/src/lib/long-press/long-press.directive.ts
  - frontend/src/app/pages/applications/applications-list.component.html
  - frontend/src/app/pages/applications/attachments-panel.component.html
  - frontend/src/app/pages/expenses/expenses.component.html
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# A long press selects in every list with a multiple selection

Every list that has a multiple selection must start it with a long press on a row (spec
000211). The long press selects the pressed row. In the selection, a long press toggles the
row. The lists are the Anträge, the Buchungen and the Anhänge of an Antrag.

The long press must not open the row. A list uses the long press of the kit
(`appLongPress`), so the context menu key and Shift+F10 start the selection too. The
entry `Mehrere auswählen` and the checkboxes stay as the path with one tap, for a
keyboard and for a screen reader (spec 000514).

A person who cannot use the selection gets no long press.

Reason: The long press started the selection in the Buchungen, but not in the Anträge.
