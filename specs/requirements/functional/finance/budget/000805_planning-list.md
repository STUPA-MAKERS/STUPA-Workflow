---
id: "000805"
title: The list of Planung shows the plan as a tree
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-12
implementation: null
scope:
  - frontend/src/app/pages/budget
---

# The list of Planung shows the plan as a tree

In the view Planung the list must show the Kostenstellen of the plan as a tree with the
Ansatz of each Kostenstelle, in the groups "Einnahmen" and "Ausgaben" with the sum of each
group. The list must have two filter chips: the fiscal year and the version. The version
chip must name the Stammplan and each Nachtrag.

Reason: The view keeps the list and detail geometry of the Budget tab, and one plan belongs
to one fiscal year and one version.
