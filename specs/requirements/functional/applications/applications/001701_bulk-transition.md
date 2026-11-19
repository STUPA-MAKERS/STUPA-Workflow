---
id: "001701"
title: A bulk transition offers only transitions allowed for every selected Antrag
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
implementation: null
scope:
  - backend/app/modules/applications
  - frontend/src/app/pages/applications
---

# A bulk transition offers only transitions allowed for every selected Antrag

`Übergang auslösen` (`Fire transition`) must offer only a manual transition that the person may
fire on every selected Antrag. The server must check the guard of each Antrag again when it
fires. A transition into a state with the flag `Bewilligt` must use the requested amount of each
Antrag as its approved amount (001610), and the dialog must list these amounts before the person
confirms.

Reason: A transition that is wrong for one Antrag of the selection must not show as a choice for all of them.

Test: A backend integration test fires a bulk transition where one guard fails at the fire.
