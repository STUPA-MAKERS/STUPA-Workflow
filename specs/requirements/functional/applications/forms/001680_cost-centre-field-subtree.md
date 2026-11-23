---
id: "001680"
title: A Kostenstelle field can limit its picker to a subtree
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
implementation:
  - backend/app/modules/forms/service.py
  - backend/app/modules/budget/form_options.py
  - frontend/src/app/pages/admin/forms/form-editor.component.ts
  - frontend/vendor/ui-kit/views/form-editor/src/form-editor-view.component.ts
scope:
  - backend/app/modules/forms
  - backend/app/modules/budget
  - frontend/src/app/shared/formly
  - frontend/src/app/pages/admin/forms
---

# A Kostenstelle field can limit its picker to a subtree

A `budget_select` field must have the setting `Wurzel` (`Root`) in the form editor. The value is
the key path of a Kostenstelle, for example `QSM`. When it is set, the picker must offer only the
Kostenstellen below this node in the fiscal year. The node itself must not be selectable. The
leaf rule of 001031 still applies, so only a leaf below the root is selectable.

Reason: The picker shows 54 nodes, among them the roots QSM and VSM. Prod data holds one Anschaffung on QSM. A key path stays the same across fiscal years, while the id of a Kostenstelle does not.

Test: A frontend unit test renders the picker with a root. A backend unit test reads the options of a field with a root.
