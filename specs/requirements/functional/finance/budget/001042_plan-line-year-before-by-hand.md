---
id: "001042"
title: A plan line can set the Ansatz and the Ist of the year before by hand
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "backend/tests/unit/modules/budget/test_plan_export.py:test_a_value_set_by_hand_wins_and_the_rows_above_sum_it"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_line_sets_the_year_before_by_hand"
  - "frontend/src/app/pages/budget/plan/budget-plan.util.spec.ts:BudgetPlanUtil"
  - "frontend/src/app/pages/budget/plan/budget-plan.component.spec.ts:BudgetPlanComponent"
implementation:
  - backend/app/modules/budget/plan_models.py
  - backend/app/modules/budget/plan_export.py
  - backend/app/modules/budget/tree/plans.py
  - backend/app/modules/budget/tree/plan_exports.py
  - backend/app/modules/budget/plan_router.py
  - frontend/src/app/pages/budget/plan/budget-plan.util.ts
  - frontend/src/app/pages/budget/plan/budget-plan.component.ts
  - frontend/src/app/pages/budget/plan/budget-plan.component.html
scope:
  - backend/app/modules/budget
  - frontend/src/app/pages/budget/plan
---

# A plan line can set the Ansatz and the Ist of the year before by hand

A line of a Haushaltsplan version (a Titel or a Kostenstelle) can carry two optional values
that replace the figures of the year before: **Ansatz <Vorjahr> (von Hand)** and
**Ist <Vorjahr> (von Hand)**. Each value is optional on its own.

- A value set by hand must win over the figure that the line takes from its Vorgänger or
  its own Kostenstelle (001040) and over the sum of the rows below (001041). The other
  value of the line keeps its computed figure.
- A row that sums the rows below (001041) must use the values set by hand of those rows.
  The sums of a side follow.
- The values are set in the **detail of a line on the plan page**, only while the version
  is a draft (`budget.structure`), next to the Vorgänger. An empty field clears the value,
  and the line then shows the computed figure again. A value must be 0 or more, in euros
  with cents. Next to each field the detail shows the computed figure, so it is visible
  which value is set by hand. The tables, the XLSX and the PDF show the value without a
  mark.
- The values hold on the plan page, in the detail of a line, in the XLSX and in the PDF
  file (000875) and in the plan as Anlage of a protocol (000876).
- **Without a plan in force in the year before**, the columns of the year before must show
  when at least one line of the version has a value set by hand (an exception to 000889).
  Every other line then shows no figure in these columns.
- A Nachtrag takes the values over from the version before. A plan copied from the year
  before (000837) starts without them, because that year is not the year before of its
  source.
- A change of a value is part of the audit record of the line, like the amount.

Reason: The figures of the year before are not always in the platform, for example for the
first year that is planned here, or when a Kostenstelle of the year before was split in a
way that no Vorgänger expresses.

Test: Backend test: set, clear and refuse a value (negative, version not a draft); the export
shows a value set by hand instead of the computed figure, a row with rows below sums it,
and the columns show without a plan in the year before. Component test: the fields in the
detail of a line and the rows.
