---
id: "000931"
title: The dialogs of the Haushalt close on Back
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
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

# The dialogs of the Haushalt close on Back

The dialogs "Haushalt bearbeiten" and "Kostenstelle anlegen" must be kit dialogs, so that Back
closes them (ui-kit:002290).

Reason: A person who edits the Haushalt on a phone must not lose the page by a step back.
