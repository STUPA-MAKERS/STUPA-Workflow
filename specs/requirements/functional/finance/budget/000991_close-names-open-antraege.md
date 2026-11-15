---
id: "000991"
title: The close of a fiscal year names what stays open, and an Antrag can leave a closed year
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-15
tests:
  - "backend/tests/integration/modules/budget/test_budget_tree_service.py:test_the_close_names_open_antraege_and_they_move_to_an_open_year"
  - "backend/tests/unit/modules/budget/test_fiscal_year_close.py:test_move_out_of_closed_year_into_an_open_year"
  - "frontend/src/app/pages/admin/budgets/admin-budgets.component.spec.ts:AdminBudgetsComponent"
implementation:
  - backend/app/modules/budget/tree/fiscal_years.py
  - backend/app/modules/budget/tree/applications.py
  - frontend/src/app/pages/admin/budgets/admin-budgets.component.ts
scope:
  - backend/app/modules/budget
  - frontend/src/app/pages/admin
---

# The close of a fiscal year names what stays open, and an Antrag can leave a closed year

The dialog of the close of a fiscal year must name how many Anträge of the year are not in an
end state. It must also say when the plan of the year has a Nachtrag that is still a draft. The
close must stay possible in both cases.

An Antrag in a closed fiscal year must be able to move to a year that an assignment can take
(000879): with the move of the fiscal year, and with the assignment of a Kostenstelle in such a
year. The assignment of an Antrag in a closed year must not be cleared: that answers 409
`fiscal_year_closed`. A booking that is bound to the Antrag keeps its year.

Reason: An Antrag that is still open when its year closes can take no booking and no decision
on money. Without a way out, a person must reopen the whole year for one Antrag. A person who
closes a year must see what the close leaves behind. A draft of a Nachtrag is frozen by the
close, so the person must know of it too.

Test: Integration test: the check counts the open Anträge and not the ones in an end state;
after the close an Antrag moves to an open year and takes a Kostenstelle in an open year, and
the clear of the assignment is refused. Component test: the dialog shows the count and the
sentence on the Nachtrag.
