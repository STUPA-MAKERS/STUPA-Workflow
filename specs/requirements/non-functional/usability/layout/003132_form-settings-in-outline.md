---
id: "003132"
title: The settings of a form are entries of the outline
kind: non-functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-28
tests:
  - "frontend/src/app/pages/admin/forms/form-editor.component.spec.ts:adminFormOutline"
implementation:
  - frontend/vendor/ui-kit/views/form-editor
scope:
  - frontend/src/app/pages/admin/forms
  - frontend/vendor/ui-kit/views/form-editor
---

# The settings of a form are entries of the outline

In the detail pane, the form editor must show two columns: the outline and the editor of the
selected entry. The outline must start with the entries "Formular", "Regeln" and "Versionen",
above the groups. A selected entry must open its card in the second column: "Formular" the
title, the description and the switches of the form, "Regeln" the rules, "Versionen" the
version history. A selected group opens its questions, as before. When the pane is narrower
than two columns, the second column follows the outline.

Reason: The pane is too narrow for three columns, and the settings stay one click away.

Test: A unit test selects "Regeln" in the outline and expects the rules card in the second
column.
