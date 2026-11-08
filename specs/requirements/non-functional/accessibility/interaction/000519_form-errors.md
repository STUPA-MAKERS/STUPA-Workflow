---
id: "000519"
title: A form error is a text next to the field
kind: non-functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-08
tests:
  - "frontend/vendor/ui-kit/src/lib/focus/first-invalid.spec.ts:focusFirstInvalid"
  - "frontend/vendor/ui-kit/src/lib/currency-input/currency-input.component.spec.ts:CurrencyInputComponent"
implementation:
  - frontend/vendor/ui-kit/src/lib/focus/first-invalid.ts
  - frontend/src/app/pages/applications/capture/application-capture.component.ts
  - frontend/src/app/features/apply/status-timeline.component.ts
  - frontend/vendor/ui-kit/src/lib/currency-input/currency-input.component.ts
  - frontend/src/app/features/apply/apply-wizard.component.ts
  - frontend/src/app/pages/applications/applications-detail.component.ts
scope:
  - frontend/src/app/
  - frontend/vendor/ui-kit
---

# A form error is a text next to the field

A field error must be a text that is linked to the field with `aria-describedby`. On a
failed submit, the focus must go to the first field with an error. A required field must show
this in its label.

Reason: WCAG 3.3.1, 3.3.2 and 3.3.3.
