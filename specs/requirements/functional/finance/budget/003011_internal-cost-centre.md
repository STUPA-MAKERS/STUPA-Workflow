---
id: "003011"
title: A Kostenstelle can be marked Intern, and the Kostenstellen below it are Intern too
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-25
tests:
  - "backend/tests/integration/modules/budget/test_budget_internal.py:test_internal_is_off_at_start_and_switches_on_every_level"
  - "backend/tests/integration/modules/budget/test_budget_internal.py:test_internal_is_inherited_by_every_node_below"
  - "backend/tests/integration/modules/budget/test_budget_internal.py:test_internal_switches_while_a_plan_is_in_force"
  - "frontend/src/app/pages/budget/cost-centre/cost-centre-settings.component.spec.ts:CostCentreSettingsComponent"
implementation:
  - backend/app/modules/budget/tree_models.py
  - backend/app/modules/budget/tree_schemas.py
  - backend/app/modules/budget/tree/nodes.py
  - frontend/src/app/pages/budget/cost-centre/cost-centre-settings.component.ts
  - frontend/src/app/pages/budget/cost-centre/cost-centre-settings.component.html
scope:
  - backend/app/modules/budget
  - frontend/src/app/pages/budget
---

# A Kostenstelle can be marked Intern, and the Kostenstellen below it are Intern too

The settings of a Kostenstelle must have the switch "Intern". The switch must be off for a new
Kostenstelle and for every Kostenstelle that exists before this rule. The switch must exist on
every level: Haushalt, Titel and Kostenstelle.

A Kostenstelle must count as Intern when its own switch is on or when the switch of a node
above it is on. Below a node that is Intern, the switch must show on and must not be
changeable (`aria-disabled`), because only the switch of the node above turns it off. The own
value of the node below stays stored, so it applies again when the node above turns off.

The switch must stay changeable in a Haushalt whose plan is in force, in the Budget tab and in
the pane of the plan. A change of the switch must not need a draft, a Nachtrag or a vote,
because the switch changes no figure of the plan. The person who can change the other
settings of the Kostenstelle (for example "Aktiv") can change the switch. The audit log must
record the change like a change of the other settings.

Reason: Some Kostenstellen are only for the internal work of the Gremien and must not be
chosen by an applicant (003012). A whole Titel is often internal, so one switch must cover
every Kostenstelle below it.

Test: Integration tests: a new node is not Intern, the switch turns on at each level, a node
below an Intern node reads as Intern and keeps its own value, the switch changes while the
plan of the Haushalt is in force. Component test: the switch saves, and below an Intern node it
shows on and cannot change.
