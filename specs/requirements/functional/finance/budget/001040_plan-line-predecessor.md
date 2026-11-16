---
id: "001040"
title: A plan line can name its predecessor in the year before
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "backend/tests/unit/modules/budget/test_plan_rules.py:test_a_predecessor_takes_its_line_of_the_year_before_from_its_own_cost_center"
  - "backend/tests/unit/modules/budget/test_plan_export.py:test_a_predecessor_takes_the_figures_of_the_year_before"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_line_compares_with_its_predecessor"
  - "frontend/src/app/pages/budget/plan/budget-plan.util.spec.ts:BudgetPlanUtil"
  - "frontend/src/app/pages/budget/plan/budget-plan.component.spec.ts:BudgetPlanComponent"
implementation:
  - backend/app/modules/budget/plan_rules.py
  - backend/app/modules/budget/plan_export.py
  - backend/app/modules/budget/tree/plans.py
  - backend/app/modules/budget/plan_router.py
  - frontend/src/app/pages/budget/plan/budget-plan.util.ts
  - frontend/src/app/pages/budget/plan/budget-plan.component.ts
  - frontend/src/app/pages/budget/plan/budget-plan.component.html
scope:
  - backend/app/modules/budget
  - frontend/src/app/pages/budget/plan
---

# A plan line can name its predecessor in the year before

A line of a Haushaltsplan version (a Titel or a Kostenstelle) can name a **Vorgänger**: one
line of the plan in force of the year before (000889). The Vorgänger is optional.

- **Without a Vorgänger** the line compares with the line of the same Kostenstelle in the
  plan of the year before, as today. A new name or a new key of the Kostenstelle does not
  break this match, because the match is the Kostenstelle itself, not its key.
- **With a Vorgänger** the line compares with the Vorgänger instead: the "Ansatz <Vorjahr>",
  the "Ist <Vorjahr>" (the booked amount of the Vorgänger, income for the income side) and
  the "Änderung" of the plan page, the detail of a line, the XLSX and the PDF file (000875)
  and the plan as Anlage of a protocol (000876).
- A line of the year before compares with **at most one** line. When a line names it as
  Vorgänger, the line of the same Kostenstelle no longer compares with it and shows no
  figure of the year before, unless it names a Vorgänger of its own. So the sums of the
  year before count each line of that year once. A Vorgänger that another line of the
  version names answers 409 `plan_predecessor_taken`.
- The Vorgänger must be on the **same side** (Einnahme/Ausgabe) as the line. A Vorgänger
  on the other side answers 422 `plan_predecessor_invalid`, as does a Vorgänger that is
  not a line of the plan in force of the year before. A Titel that changes its side takes
  the Vorgänger off its own line and off each line below it.
- The Vorgänger is chosen in the **detail of a line on the plan page**, only while the
  version is a draft (`budget.structure`), from a list of the lines of the plan in force
  of the year before (key and name). "Kein Vorgänger" clears it. Without a plan in force
  in the year before, the field does not show.
- The Vorgänger belongs to the line of a version. A Nachtrag takes it over from the
  version before. A plan copied from the year before (000837) starts without Vorgänger,
  because that year is not the year before of its source.
- A change of the Vorgänger is part of the audit record of the line, like the amount.

Reason: Kostenstellen change from year to year. A new Kostenstelle that continues an old
one has no figures of the year before, and the comparison then shows the whole amount as
Änderung.

Test: Backend test: set, clear and refuse a Vorgänger (other side, not in the plan of the
year before, version not a draft); the export takes the figures of the Vorgänger and drops
those of the line of the same Kostenstelle. Component test: the rows and the field in the
detail of a line.
