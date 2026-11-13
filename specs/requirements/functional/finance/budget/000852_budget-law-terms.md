---
id: "000852"
title: The budget pages use the words Haushalt, Titel, Ansatz and Haushaltsplan
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-13
tests:
  - "frontend/src/app/core/i18n/translations.spec.ts:BudgetTerms"
  - "frontend/src/app/pages/budget/plan/budget-plan.component.spec.ts:BudgetPlanComponent"
  - "frontend/src/app/pages/budget/budget-dashboard.component.spec.ts:BudgetDashboardComponent"
  - "frontend/src/app/pages/budget/cost-centre/cost-centre-create.component.spec.ts:CostCentreCreateComponent"
  - "backend/tests/unit/modules/budget/test_plan_rules.py:test_version_name"
implementation:
  - frontend/src/app/core/i18n/catalog/de.json
  - frontend/src/app/pages/budget/cost-centre/cost-centre.util.ts
  - backend/app/modules/budget/plan_rules.py
scope:
  - frontend/src/app/core/i18n/catalog
  - frontend/src/app/pages/budget
  - frontend/src/app/pages/admin
  - backend/app/modules/budget
---

# The budget pages use the words Haushalt, Titel, Ansatz and Haushaltsplan

The German texts of the platform must name the parts of the budget tree as follows.

1. The top level of the tree is a "Haushalt" (plural "Haushalte"). This holds for the menu
   entry, the page in the Verwaltung, the headings, the buttons, the dialogs, the toasts,
   the error texts and the names of the audit entries. It holds for every top level, with
   or without a Haushaltsplan.
2. A Kostenstelle directly below a Haushalt is a "Titel". A text that names this level
   alone must say "Titel": the heading of the section of such a node, the dialog that
   creates a node below a Haushalt, the column heading of the plan, and the error texts
   about the side. A node below a Titel stays a "Kostenstelle", and a text that
   holds for a node of any level keeps "Kostenstelle".
3. The amount of a node for a fiscal year is its "Ansatz" when the Haushalt has a
   Haushaltsplan, in the tree and in the section of the node as in the plan. For a Haushalt
   without a Haushaltsplan it stays the "Zuteilung".
4. The first version of a plan is the "Haushaltsplan". The word "Stammplan" must not show,
   also not in the names that the server writes. The question of the vote of a step
   names a Nachtrag and leaves the first version out, because the question starts with
   "Haushaltsplan".

Every other word stays: "Ist", "Ausgegeben", "Gebunden", "Gesperrt", "Nachtrag", "Seite",
"Schlüssel", "Haushaltsjahr". The texts of other areas stay too: "Mit Budget" and "Ohne
Budget" of an Antragsart, the names of the flow actions and guards, the names of the
permissions and of the scopes of an access token. The routes, the API, the data and the
English texts stay, except "Base plan", which becomes "Budget plan".

Reason: The draft Finanzordnung (§ 4) and the Landeshaushaltsordnung name the plan of the
Studierendenschaft a Haushaltsplan that consists of Titel with an Ansatz each, and
§ 65b LHG speaks of the "Haushalt der Studierendenschaft". "Budget" names a part of a
Haushalt that someone manages, so it misleads as the name of the level above the Titel. Two
words for one amount ("Zuteilung" and "Ansatz") make a reader look for a difference that
does not exist. The other words are the ones that other Studierendenschaften use, so a
change would only cost the readers.

Test: A test of the catalog reads every German text and finds neither "Budget" outside the
listed areas nor "Stammplan". The component tests of the tree, of the section and of the
plan read "Titel" for a node below a Haushalt and "Kostenstelle" for a node below it, and
"Ansatz" or "Zuteilung" by the plan switch of the Haushalt. A backend test reads the name
of the first version.
