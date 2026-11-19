---
id: "001610"
title: Every approval asks for the approved amount
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-19
implementation: null
scope:
  - backend/app/modules/applications
  - frontend/src/app/pages/applications
---

# Every approval asks for the approved amount

A manual transition from a state without the flag `Bewilligt` into a state with the flag
`Bewilligt` (000571) must open the decision dialog. The dialog must show the field
`Genehmigter Betrag` (`Approved amount`), preset with the requested amount. The field is
required. The conditions (`Auflagen`) stay optional. The server must refuse such a transition
without `approvedAmount` with 422 `approved_amount_required`. A transition between two states
with the flag `Bewilligt` must not ask again.

Reason: In prod the approved amount is empty in 79 of 79 Anträge. An empty value means 'as requested', so nobody can see if a person checked the amount.

Test: A backend unit test fires a transition into an approved state without and with `approvedAmount`.
