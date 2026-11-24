---
id: "002843"
title: The form builder makes a computed field the amount
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation:
  - frontend/vendor/ui-kit/views/form-editor/src/form-editor-view.component.ts
scope:
  - frontend/src/app/pages/admin/forms
---

# The form builder makes a computed field the amount

The form builder must show the switch `Ist der Antragsbetrag` (`Is the application amount`) at
a `computed` field. The switch must set `isPromoted: true` and `promoteTarget: "amount"`, and
off it must remove both.

Reason: The admin must be able to set the computed amount without editing JSON.

Test: The unit test of the form editor view turns the switch on and off at a computed field.
