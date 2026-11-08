---
id: "000544"
title: A Vorgänger chosen at creation prefills the form
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-08
implementation: null
scope:
  - backend/app/modules/applications
  - frontend/src/app/features/apply
  - frontend/src/app/pages/applications
---

# A Vorgänger chosen at creation prefills the form

In the apply wizard and in "Antrag erfassen", the user must be able to choose a Vorgänger
before the first form step. The choice must fill the new form with the answers of the
Vorgänger. Only an answer whose field key exists in the new form version and whose value is
valid there must be copied. File fields must stay empty. A PII field must stay empty when the
caller cannot read the PII of the Vorgänger. The user must be able to change every prefilled
answer before "Antrag anlegen". The new Antrag must save the Vorgänger as its link.

Reason: A Folgeantrag mostly repeats the earlier Antrag, so the user only changes what is new.
A copy by field key works across form versions. A copied file would be a second copy of a
document that the new Antrag may not need.

Test: Unit tests of the prefill read: a removed field, an invalid value, a file field and a
PII field without the right are not in the result. A frontend test checks that the wizard
fills the form and keeps it editable.
