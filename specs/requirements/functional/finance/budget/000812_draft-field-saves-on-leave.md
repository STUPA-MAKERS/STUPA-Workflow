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
show its cause and the saved value again, and must keep the line open, so the next field
keeps its focus and its text. The table must not have a save button. A saved field must not show a toast, because the new
sums show the save. An answer that arrives after the person started to leave the page must
not change the URL, so a press on a link beside the field saves the field and opens
the link. An answer for a plan of another year or another budget than the chosen one must
not come onto the page, so a field never changes a version that the page does not name. An answer that is older than the plan on the page must not replace it, so the page never shows an amount that is
no longer the saved one. The server can take two requests in another order than the page sent
them, so after answers in another order than their requests the page must read the plan once
more. A text that the person types in a field must stay in that field of that line: the answer
of a save must not replace it, and another line must not show it, also the line of the same
Kostenstelle in another year. The same holds for the press of a Vermerk. A field that the person sets back to the value
before while its save runs must be saved again. An amount field must show the amount of its
save that runs, also after the answer of an earlier save of that field.

Reason: A draft does not bind, and a value that is saved at once is not lost when the tab
closes. Two fields that save one after the other must not overwrite each other.

Test: The component tests leave a changed field and read the request, and a refused save shows
the saved value again, and a saved field shows no toast. A test answers a save
while a navigation to another page runs and after the page is gone, and reads that no URL is
written. A test answers a read and a save after the person chose another year and reads that the page shows the chosen year. A test does the same for the answer of a new Kostenstelle. One test answers two requests in the other order and reads the newer plan. One test types an Erläuterung while its save runs and then selects another line, and one answers two saves in the other order and reads the plan that the page reads then. One test presses a Vermerk and types an Erläuterung, chooses another year before the answers and reads both lines. One test presses a Vermerk twice while the first save runs and reads two requests. One test presses a Vermerk three times and one types an Erläuterung three times while the first save runs, and each reads the last press or text after the answers of the older saves. One test sets a Vermerk back while its save runs and after a save of the other Vermerk of the line ended, and reads three requests. One test saves an Ansatz twice and reads the last amount in the field after the answer of the first save. One test presses a Vermerk whose save is refused and reads the saved state of the switch. The backend test sends two requests that each name one field.
