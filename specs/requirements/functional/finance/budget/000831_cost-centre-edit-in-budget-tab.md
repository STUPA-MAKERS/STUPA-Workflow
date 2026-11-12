---
id: "000831"
title: A Kostenstelle is edited in the Budget tab
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-12
implementation: null
scope:
  - frontend/src/app/pages/budget
---

# A Kostenstelle is edited in the Budget tab

The detail of a selected Kostenstelle in the Budget tab must show the section
"Kostenstelle" with its key, its name, its colour, the switch "Aktiv", the Gremium that
sees it and the Gremium that decides. For a direct child of a budget with the plan switch
on, the section must also show the side (000817). A person with `budget.structure` must
change each field there, and the platform must save a field when the person leaves it. A
person without `budget.structure` must not see the section. The state of the plan version
must not lock these fields, because a decided version keeps its own name and key (000821).

Reason: The settings of a Kostenstelle stand beside its amounts, so one place holds all
that a person sets on it.
