---
id: "000129"
title: An Antrag stays open after a transition in Aufgaben
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-06
implementation:
  - frontend/src/app/pages/tasks
scope:
  - frontend/src/app/pages/tasks
---

# An Antrag stays open after a transition in Aufgaben

In Aufgaben, an Antrag must stay open after a status transition. Aufgaben must not close it and
must not open the next task.

Reason: The automatic next task confused users several times.
