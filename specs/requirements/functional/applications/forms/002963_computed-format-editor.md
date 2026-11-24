---
id: "002963"
title: The form builder sets the format of a computed field
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
implementation:
  - frontend/vendor/ui-kit/views/form-editor/src/form-editor-view.component.ts
scope:
  - frontend/src/app/pages/admin/forms
---

# The form builder sets the format of a computed field

The form builder must show the select `Anzeigeformat` (`Display format`) below the expression of
a `computed` field, with the options `Zahl`, `Geldbetrag` and `Prozent` (`Number`, `Money`,
`Percent`). `Zahl` must remove `format`. The form builder must not show the select when the
field is the amount (002843).

Reason: The admin must be able to set the format without editing JSON. The amount is always
money, so a select for it offers a choice that does nothing.

Test: The unit test of the form editor view sets `percent` and then `Zahl` at a computed field,
and finds no select at the amount field.
