---
id: "001670"
title: A form version has rules across fields
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
implementation:
  - backend/app/shared/config_schemas.py
  - backend/app/modules/forms/service.py
  - backend/app/modules/admin/service/forms.py
  - frontend/src/app/pages/admin/forms/form-editor.component.ts
  - frontend/vendor/ui-kit/views/form-editor/src/form-editor-view.component.ts
scope:
  - backend/app/modules/forms
  - frontend/src/app/features/apply
  - frontend/src/app/pages/admin/forms
---

# A form version has rules across fields

A form version must have a list `rules`. A rule must have:

- `logic`: a JsonLogic expression with only the allowed operators (000285). It is true when the
  answers meet the rule.
- `message`: a text in German and in English.
- `severity`: `block` or `warn`.

The expression must read the answers by field key, `amount` (the amount of the Antrag) and
`costTotal` (the sum of the preferred offers). The form editor must have a section `Regeln`
(`Rules`) to add, change, order and remove rules.

Reason: Prod data holds 6 Anträge where a rule of the Antragsart was explained only in a comment, for example the QSM minimum of 500 €.

Test: A backend unit test saves a form with a rule and refuses a rule with an operator that is not allowed.
