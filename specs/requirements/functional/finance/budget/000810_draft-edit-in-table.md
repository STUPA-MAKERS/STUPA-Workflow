---
id: "000810"
title: A draft is edited in the table
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-14
tests:
  - "frontend/src/app/pages/budget/plan/budget-plan.component.spec.ts:BudgetPlanComponent"
implementation:
  - frontend/src/app/pages/budget/plan/budget-plan.component.ts
scope:
  - frontend/src/app/pages/budget
---

# A draft is edited in the table

On a wide screen, the column Ansatz of a draft must show one amount field in each row that
has no child. A press on a row must select its Kostenstelle, and the detail must show the
fields Ansatz and Erläuterung. On a phone a press on a row must open a bottom sheet with
these fields and the table must not show fields. Each field must be read-only when the
version is not in `draft`.

The amount field of a table must show each Ansatz of the plan and each typed amount in
full. It has a narrow form, with which the five columns of a draft with a year before must
fit the table area from a window width of 1280 px. It must take a wider form when the
version holds an Ansatz from 10 million euro, and from the moment a person types such an
amount in the version: the form must not change back while the save of that amount runs.
With the wider form the table can scroll in its own area.

Reason: A plan has many lines, and one sheet for each amount costs too many steps. The
Ansatz of a parent is the sum of its children.

Test: The component tests press a row on a wide screen and on a phone and read the fields of a
draft and of a decided version. One test types an Ansatz of 10 million euro, leaves the
field and reads the wide form of the fields while the save runs, and one reads it for a plan that
holds such an Ansatz.
