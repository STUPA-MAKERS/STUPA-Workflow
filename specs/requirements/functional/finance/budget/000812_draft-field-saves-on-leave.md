---
id: "000812"
title: An amount field of a draft saves when the person leaves it
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-13
tests:
  - "frontend/src/app/pages/budget/plan/budget-plan.component.spec.ts:BudgetPlanComponent"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_line_request_changes_only_the_fields_it_names"
implementation:
  - frontend/src/app/pages/budget/plan/budget-plan.component.ts
  - backend/app/modules/budget/tree/plans.py
scope:
  - frontend/src/app/pages/budget
  - backend/app/modules/budget
---

# An amount field of a draft saves when the person leaves it

A field of a draft line must save its value when the person leaves the field: the Ansatz,
the Erläuterung, the gesperrt amount and each Vermerk. The request must hold only the
changed field, and the platform must keep each field of the line that a request does not
name. The plan page must then show the new sums and the new balance. A refused save must
show its cause and the saved value again. The table must not have a save button. A saved field must not show a toast, because the new
sums show the save. An answer that arrives after the person started to leave the page must
not change the URL, so a press on a link beside the field saves the field and opens
the link. An answer for a plan of another year or another budget than the chosen one must
not come onto the page, so a field never changes a version that the page does not name.

Reason: A draft does not bind, and a value that is saved at once is not lost when the tab
closes. Two fields that save one after the other must not overwrite each other.

Test: The component tests leave a changed field and read the request, and a refused save shows
the saved value again, and a saved field shows no toast. A test answers a save
while a navigation to another page runs and after the page is gone, and reads that no URL is
written. A test answers a read and a save after the person chose another year and reads that the page shows the chosen year. The backend test sends two requests that each name one field.
