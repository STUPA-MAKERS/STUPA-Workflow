---
id: "001041"
title: A row without its own figure of the year before sums the rows below it
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-16
tests:
  - "backend/tests/unit/modules/budget/test_plan_export.py:test_a_row_without_its_own_match_sums_the_rows_below"
  - "frontend/src/app/pages/budget/plan/budget-plan.util.spec.ts:BudgetPlanUtil"
implementation:
  - backend/app/modules/budget/plan_export.py
  - frontend/src/app/pages/budget/plan/budget-plan.util.ts
scope:
  - backend/app/modules/budget
  - frontend/src/app/pages/budget/plan
---

# A row without its own figure of the year before sums the rows below it

A row of a Haushaltsplan version has rows below it when it is a Titel or a Kostenstelle
with Kostenstellen below. The Vorgänger of the lines (001040) is the mapping to the year
before. This rule makes the figures of the year before follow that mapping upward too.

- A row with rows below that **compares with nothing** of the year before must take as
  "Ist <Vorjahr>" the **sum of the Ist of the rows directly below it**. A row compares
  with nothing when it has no Vorgänger and its own Kostenstelle is the Vorgänger of
  another line, or when its match has no line in the plan in force of the year before
  (for example a new Kostenstelle). The sum goes up level by level, so a Titel sums its rows below
  even when they are sums themselves.
- The same holds for the "Ansatz <Vorjahr>" and for the "Änderung" that follows from it.
- A row with a Vorgänger, or with its own Kostenstelle as match, keeps its own figures.
- A row **without rows below** that compares with nothing of the year before (no line of
  its Kostenstelle or of its Vorgänger in the plan in force of the year before) must show **no
  Ist** (it must not show "0,00"), as it shows no Ansatz of the year before. Its own bookings of that year
  do not count, because the plan of that year had no line for them.
- The sums of a side ("Summe Einnahmen", "Summe Ausgaben") and the balance add the Titel,
  as today. Because a Titel without its own match now carries the sum of its rows below,
  these sums show the figures of the year before as the mapping gives them.
- This holds on the plan page, in the detail of a line, in the XLSX and in the PDF file
  (000875) and in the plan as Anlage of a protocol (000876).

Reason: with Vorgänger set on the Kostenstellen only, a new Titel compares with nothing.
The PDF then shows an empty Ist for the Titel and "0,00" in "Summe Einnahmen" and
"Summe Ausgaben", although the Kostenstellen below carry Ist amounts.

Test: Unit test of the export: a Titel without a match sums the Ist and the Ansatz of the
year before of its rows below, the side sums follow, and a line without a match shows no Ist. Component test: the same on the
plan page.
