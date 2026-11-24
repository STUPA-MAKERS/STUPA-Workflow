---
id: "003002"
title: The files per position are a setting of the positions field
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
tests:
  - "frontend/src/app/shared/formly/types/formly-positions.type.spec.ts:position files"
implementation:
  - backend/app/shared/config_schemas.py
  - frontend/src/app/shared/formly/types/formly-positions.type.ts
  - frontend/vendor/ui-kit/views/form-editor/src/form-editor-view.component.html
scope:
  - backend/app/modules/forms
  - frontend/src/app/shared/forms
  - frontend/src/app/pages/admin/forms
---

# The files per position are a setting of the positions field

A `positions` field must have the setting `validation.positionFiles`. The default is on. When it
is off, the form must not show the upload of 001730 below a position of this field. The Antrag
keeps its general attachments. The form editor must show the switch `Dateien je Position`
(`Files per position`) at a `positions` field.

Reason: Some forms collect the offers as general attachments. An upload per position then shows
a second place for the same files.

Test: A frontend unit test renders a position with the setting off and finds no files block.
