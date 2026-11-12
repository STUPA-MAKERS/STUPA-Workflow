---
id: "000818"
title: A plan line makes a Kostenstelle part of the year
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-12
implementation: null
scope:
  - backend/app/modules/budget
---

# A plan line makes a Kostenstelle part of the year

A Kostenstelle must be part of a fiscal year with a Haushaltsplan when the version in force
has a line for it. A line with an Ansatz of 0 € must count. A Kostenstelle without a line
must stay in the tree and in the other years.

Reason: The Haushaltsplan of a year names its Titel, and the set of Titel changes from year
to year. One tree for all years needs the plan to say which Kostenstellen a year has.
