---
id: "003012"
title: The form does not offer an internal Kostenstelle
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-25
tests:
  - "backend/tests/integration/modules/budget/test_budget_internal.py:test_the_form_field_does_not_offer_an_internal_cost_centre"
  - "backend/tests/integration/modules/budget/test_budget_internal.py:test_an_antrag_with_an_internal_cost_centre_is_refused"
  - "backend/tests/integration/modules/budget/test_budget_internal.py:test_an_old_answer_with_an_internal_cost_centre_does_not_block_an_edit"
  - "backend/tests/unit/modules/flow/test_flow_extras_dispatcher.py:test_assign_budget_from_field_skips_an_internal_cost_centre"
implementation:
  - backend/app/modules/budget/form_options.py
  - backend/app/modules/applications/service/form_checks.py
  - backend/app/modules/flow/extras_dispatcher.py
scope:
  - backend/app/modules/budget
  - backend/app/modules/applications
  - backend/app/modules/flow
---

# The form does not offer an internal Kostenstelle

A form field of the type `budget_select` must not offer a Kostenstelle that is Intern (003011).
This applies to the public form, to the form of an Antrag on behalf of an applicant and to the
edit of an Antrag.

- The server must refuse an answer that names an Intern Kostenstelle with 422
  `cost_centre_internal`, when the Antrag is created and when an edit changes that field.
- An older answer that names a Kostenstelle that became Intern later must stay, stay readable
  and must not block the edit of another field.
- The flow action that assigns the Kostenstelle of a form field (`assignBudgetFromField`) must
  do nothing when the Kostenstelle is Intern.

Every other place must still offer an Intern Kostenstelle: the dialog that assigns a
Kostenstelle to an Antrag, the bookings and transfers, the filters, the plan, and the pickers
of the flow editor.

Reason: An Intern Kostenstelle is for the internal work of the Gremien. An applicant must not
choose it, but a member who works on an Antrag must still be able to assign it.

Test: Integration tests: the options of the field leave out an Intern Kostenstelle and every
node below it, a create with one is refused with 422 `cost_centre_internal`, an edit of another
field of an Antrag with an older Intern answer is taken. Unit test: `assignBudgetFromField`
skips an Intern Kostenstelle.
