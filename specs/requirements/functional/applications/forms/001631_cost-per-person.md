---
id: "001631"
title: The cost line shows the amount per person
kind: functional
status: replaced
owner: frederikbeimgraben
updated: 2026-11-24
replaced_by: F/applications/forms/003010
scope:
  - backend/app/modules/forms
  - frontend/src/app/features/apply
  - frontend/src/app/pages/admin/forms
---

# The cost line shows the amount per person

A `number` field must have the switch `Teilnehmerzahl` (`Number of participants`) in the form
editor. A form must have at most one field with this switch. When the form has this field and its
value is greater than 0, the line of 001630 must add `Z € pro Person` (`Z € per person`). Z is
Y divided by the number of participants, rounded to the cent.

Reason: Some Antragsarten have a limit per person, so the applicant and the reviewer must see this value.

Test: A backend unit test refuses a form with two such fields. A frontend unit test checks the value per person.
