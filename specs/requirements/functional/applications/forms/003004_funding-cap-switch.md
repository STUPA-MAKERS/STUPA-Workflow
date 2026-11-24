---
id: "003004"
title: The cap of the funding at the total cost is a setting
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-24
tests:
  - "backend/tests/unit/modules/forms/test_forms_validation.py:test_funding_cap_setting"
  - "frontend/src/app/shared/forms/formly-mapper.spec.ts:funding cap"
implementation:
  - backend/app/shared/config_schemas.py
  - backend/app/modules/forms/validation.py
  - frontend/src/app/shared/forms/formly-mapper.ts
  - frontend/vendor/ui-kit/views/form-editor/src/form-editor-view.component.html
scope:
  - backend/app/modules/forms
  - frontend/src/app/shared/forms
  - frontend/src/app/pages/admin/forms
---

# The cap of the funding at the total cost is a setting

A `funding` field must have the setting `validation.capAtCost`. The default is on. When it is on,
the form and the server must refuse a value above the cost total (000135). When it is off, they
must accept it. The form editor must show the switch `Höchstens die Gesamtkosten`
(`At most the total cost`) at a `funding` field.

Reason: A flat-rate grant can be higher than the listed costs. A form rule (001670) can still set
any other limit.

Test: A backend unit test accepts a funding above the cost total with the setting off and refuses
it with the setting on. A frontend unit test shows no error with the setting off.
