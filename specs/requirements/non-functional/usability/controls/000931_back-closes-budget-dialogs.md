---
id: "000931"
title: Back closes the dialogs of the Haushalt
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
tests:
  - "frontend/src/app/shared/util/close-on-back.spec.ts:closeOnBack"
implementation:
  - frontend/src/app/shared/util/close-on-back.ts
  - frontend/src/app/pages/budget/cost-centre/cost-centre-create.component.ts
  - frontend/src/app/pages/admin/budgets/admin-budgets.component.ts
scope:
  - frontend/src/app/pages/budget
  - frontend/src/app/pages/admin/budgets
  - frontend/src/app/shared/util
---

# Back closes the dialogs of the Haushalt

The dialogs "Haushalt bearbeiten" and "Kostenstelle anlegen" must each be an entry in the
history of the browser while they are open. "Back" must close the open dialog and must keep
the page behind it. A close by a button must take the entry away again.

Reason: On a phone "back" is the usual way to close what lies on top. Without an entry the
step back leaves the page, and the person loses the place and what the dialog held.

Test: The test opens a dialog state, reads the new entry in the history, goes back and
reads that the dialog closed. It closes by a button and reads that nothing else closed, and
it reads that a page that went no longer listens.
