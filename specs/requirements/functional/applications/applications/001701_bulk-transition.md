---
id: "001701"
title: A bulk status change uses only transitions allowed for each selected Antrag
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-20
implementation:
  - backend/app/modules/flow/bulk.py
  - frontend/src/app/pages/applications/bulk-dialog/bulk-dialog.component.ts
scope:
  - backend/app/modules/applications
  - frontend/src/app/pages/applications
---

# A bulk status change uses only transitions allowed for each selected Antrag

`Status setzen` (`Set status`, 001704) must move an Antrag only by a manual transition that the
person may fire on that Antrag. The server must check the guard of each Antrag again when it
fires, and it skips an Antrag that has no such transition. A transition into a state with the flag `Bewilligt` must use the requested amount of each
Antrag as its approved amount (001610), and the dialog must list these amounts before the person
confirms.

Reason: A transition that is wrong for one Antrag of the selection must not move that Antrag.

Test: A backend integration test fires a bulk transition where one guard fails at the fire.
