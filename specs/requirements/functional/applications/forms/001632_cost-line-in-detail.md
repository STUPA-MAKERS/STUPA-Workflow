---
id: "001632"
title: The Antrag detail shows the same cost line
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
implementation: null
scope:
  - backend/app/modules/forms
  - frontend/src/app/features/apply
  - frontend/src/app/pages/admin/forms
---

# The Antrag detail shows the same cost line

The Antrag detail must show the line of 001630 and 001631 below the Kostenaufstellung, with the
same values that the form showed.

Reason: The reviewer must see the same numbers as the applicant.

Test: A frontend unit test renders the detail of an Antrag with positions, funding and a number of participants.
