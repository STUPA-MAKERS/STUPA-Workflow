---
id: "000875"
title: A version of a Haushaltsplan exports as XLSX and as PDF
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-13
tests:
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_a_version_exports_with_the_year_before_and_the_version_before"
  - "backend/tests/unit/modules/budget/test_plan_export.py:test_the_rows_follow_the_tree_and_the_sides"
  - "backend/tests/unit/modules/budget/test_plan_export.py:test_the_table_of_a_nachtrag_shows_the_version_before_and_the_change"
  - "backend/tests/unit/modules/budget/test_plan_export.py:test_the_workbook_holds_the_head_and_the_amounts_as_numbers"
  - "backend/tests/unit/modules/budget/test_plan_export.py:test_the_file_name"
  - "backend/tests/unit/modules/budget/test_plan_export.py:test_a_version_in_progress_shows_its_open_step"
  - "backend/tests/unit/modules/budget/test_plan_router.py:test_the_export_follows_the_read_rule_of_the_budget"
  - "backend/tests/unit/modules/budget/test_plan_router.py:test_the_pdf_carries_the_design_of_the_gremium"
  - "backend/tests/integration/modules/budget/test_budget_plan.py:test_the_export_takes_the_design_of_the_gremium_of_the_budget"
  - "typst/tests/test_plan.py:test_the_plan_renders_landscape_with_its_mark_on_each_page"
  - "frontend/src/app/pages/budget/plan/budget-plan.component.spec.ts:BudgetPlanComponent"
implementation:
  - backend/app/modules/budget/plan_export.py
  - backend/app/modules/budget/tree/plan_exports.py
  - backend/app/modules/budget/plan_router.py
  - backend/app/modules/files/cd_resolver.py
  - backend/app/shared/xlsx.py
  - typst/template/plan.typ
  - typst/typst_service/document.py
  - frontend/src/app/pages/budget/plan/budget-plan.component.ts
scope:
  - backend/app/modules/budget
  - backend/app/modules/files/cd_resolver.py
  - backend/app/shared/xlsx.py
  - typst
  - frontend/src/app/pages/budget/plan
---

# A version of a Haushaltsplan exports as XLSX and as PDF

The page of a Haushaltsplan must offer the shown version as an XLSX file and as a PDF file.
Each person who can read the plan can load both files. Each version exports, a draft too.

Both files must hold:

- the head: the name of the Haushalt, the fiscal year, the version ("Haushaltsplan" or
  "Nachtrag n") and its state. The XLSX file also holds the date of the export. A version that is not in force
  must show its state on each page of the PDF and in the head of the sheet: "Entwurf"
  for a draft, and for a version in progress the name of the step that it waits for,
  for example "Genehmigung Rektorat";
- the lines in the order of the plan, Einnahmen first and then Ausgaben, each with its
  sum, and then the balance of the two sums;
- per line: the key, the name, the Ansatz, the Ansatz and the Ist of the year before
  (Finanzordnung § 4 (3); both only under 000889), the Vermerke ("übertragbar", "deckungsfähig"), the blocked
  amount and the note;
- for a Nachtrag: the Ansatz of the version before it and the change.

A decided version must print the names and the keys of the decision (000808). The XLSX
file must hold the amounts as numbers. The PDF must be A4 landscape in the design of the
protocols, with the logos of the corporate design of the Gremium of the Haushalt. A
Haushalt without a Gremium or a Gremium without a design gets the logo of the StuPa. The file name must be `Haushaltsplan_<Haushalt>_<fiscal year>[_Nachtrag-n][_Entwurf]`
with the extension of the format. An export is an entry in the audit log.

Reason: The Finanzordnung (§ 7, § 9) says that the draft goes to the StuPa and the decided
plan to the Präsidium. Both get a file. The person who can read the plan on the page gets
no more data from the file.

Test: An integration test builds the export of a first plan with a year before and of a
Nachtrag with the version before. Unit tests compare the rows of the sheet and of the PDF
with the lines, load both routes with and without the view of the Haushalt, and read the
amounts of the workbook as numbers. A test of the typst service renders the plan layout.
