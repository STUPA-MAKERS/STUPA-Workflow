---
id: "001641"
title: A placeholder warning does not block the submit
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
implementation:
  - frontend/src/app/shared/formly/types/formly-positions.type.ts
scope:
  - backend/app/modules/forms
  - frontend/src/app/features/apply
  - frontend/src/app/pages/admin/forms
---

# A placeholder warning does not block the submit

A warning of 001640 must not block the submit. The backend must accept an Antrag with such an
offer when the offer meets 000133 and 000134.

Reason: A real offer can be cheap or short. The warning helps the applicant, and the reviewer decides.

Test: A frontend unit test submits a form with a warning.
