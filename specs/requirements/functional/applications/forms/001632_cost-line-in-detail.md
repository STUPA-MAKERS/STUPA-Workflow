---
id: "001632"
title: The Antrag detail shows no cost line
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
implementation:
  - frontend/src/app/shared/forms/answer-view/answer-view.component.ts
  - frontend/src/app/shared/forms/positions-view/positions-view.component.ts
scope:
  - backend/app/modules/forms
  - frontend/src/app/features/apply
  - frontend/src/app/pages/admin/forms
---

# The Antrag detail shows no cost line

The line of 001630 and 001631 must show only in the step of the form where the applicant
enters the positions. The Antrag detail and the review step of the form must not show it below
the Kostenaufstellung. They show the total of the positions and the answers for the funding and
the number of participants as their own rows.

Reason: The line repeats the total directly above it, and the detail shows the funding and the
number of participants already.

Test: A frontend unit test renders the detail of an Antrag with positions, funding and a number of participants and finds no cost line.
