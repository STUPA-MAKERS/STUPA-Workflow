---
id: "000882"
title: The Antrag PDF shows only what the reader may see
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-13
implementation:
  - backend/app/modules/applications/pdf.py
  - frontend/src/app/pages/applications
scope:
  - backend/app/modules/applications
  - backend/app/modules/pdf
  - typst
  - frontend/src/app/pages/applications
---

# The Antrag PDF shows only what the reader may see

The Antrag PDF must show the same fields as the detail page shows to the same person. It
must not show the answers of a field with `is_pii` to a person without the right of 000130,
and it must follow the observer view (000753). The PDF must show such an answer as
`(nicht sichtbar)`.

Reason: The PDF is a second way to read the Antrag. It must not show more than the page.

Test: Integration test of the route: an observer gets a PDF without the text of the PII
answers and without the applicant e-mail.
