---
id: "000804"
title: The Budget tab has the views Bewirtschaftung and Planung
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-12
implementation: null
scope:
  - frontend/src/app/pages/budget
---

# The Budget tab has the views Bewirtschaftung and Planung

The Budget tab must have the two views "Bewirtschaftung" and "Planung". The view Planung is
the plan page. A segmented switch
above the search field of the list must change the view. On a phone the switch must be below
the title. The view Planung must have the route `/budget/plan`. The switch must show only
when a top-level Kostenstelle has the plan switch on (000814).

Reason: A person must see how to go from the budget to its plan and back.
