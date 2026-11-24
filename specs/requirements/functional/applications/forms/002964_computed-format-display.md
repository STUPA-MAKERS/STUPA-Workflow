---
id: "002964"
title: A computed value shows in its format
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-24
implementation:
  - frontend/src/app/shared/formly/types/formly-display.type.ts
  - frontend/src/app/shared/forms/answer-view/answer-view.component.ts
  - backend/app/modules/documents/application_markdown.py
scope:
  - frontend/src/app/shared/forms
  - frontend/src/app/shared/formly
  - backend/app/modules/documents
---

# A computed value shows in its format

The form, the answer view and the PDF of the Antrag must show a `computed` value in its format
(002962) in the language of the text. `money` shows as an amount in EUR, for example
`1.234,50 €`. `percent` shows with at most one decimal place, for example `83,3 %` for 0.8333.
`number` shows the number as it is. A field without a value shows `—` in the form, and the
answer view and the PDF leave it out.

Reason: A reader compares the rate and the own share with the limits of the Finanzordnung. A raw
value such as `0.8333333` makes them do the conversion.

Test: The unit tests of the display type and of the answer view show `83,3 %` and `200,00 €`,
and `backend/tests/unit/modules/documents/test_application_markdown.py` writes `83,3 %` and
`200,00 €` in the PDF Markdown.
