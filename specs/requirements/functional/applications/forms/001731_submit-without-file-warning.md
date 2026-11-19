---
id: "001731"
title: A submit without a file asks for a confirmation
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
implementation: null
scope:
  - backend/app/modules/files
  - backend/app/modules/forms
  - frontend/src/app/features/apply
  - frontend/src/app/pages/applications
---

# A submit without a file asks for a confirmation

When the applicant submits an Antrag with a `positions` field and the Antrag has no attachment,
the form must show a warning. The applicant must be able to confirm the warning and submit.

Reason: Most Anträge need an offer or a receipt, but some offers come later.

Test: A frontend unit test submits without a file and checks the warning and the submit after the confirmation.
