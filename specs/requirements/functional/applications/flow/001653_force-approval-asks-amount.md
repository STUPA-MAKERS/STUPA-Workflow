---
id: "001653"
title: A forced approval asks for the approved amount
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
implementation:
  - backend/app/modules/flow/service.py
  - backend/app/modules/flow/schemas.py
  - frontend/src/app/pages/applications/force-status-dialog/force-status-dialog.component.ts
scope:
  - backend/app/modules/flow
  - frontend/src/app/pages/applications
---

# A forced approval asks for the approved amount

When the dialog `Status erzwingen` (`Force status`) moves an application with an amount from a
state without the flag `Bewilligt` into a state with the flag `Bewilligt` (000571), it must
show the field `Förderbetrag` (`Approved amount`) as in 001610, preset with the requested amount
and required. The conditions stay optional. The server must refuse such a forced move without
`decision.approvedAmount` with 422 `approved_amount_required`, and it must store the decision
with the status event. A forced move into any other state ignores a decision.

Reason: Without it a forced status is the one way left to approve without an amount (001610).

Test: A backend integration test forces an approval without and with an amount, and a move into
a rejected state with an amount that the server drops.
