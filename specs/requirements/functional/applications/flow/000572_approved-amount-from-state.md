---
id: "000572"
title: The approved amount follows the approved state
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-09
implementation: null
scope:
  - backend/app/modules/budget
  - backend/app/modules/todos
  - backend/app/modules/applications
  - backend/app/modules/flow
  - frontend/src/app/pages/budget
---

# The approved amount follows the approved state

An Antrag in an approved state (000571) must count with its approved amount: the amount of its
valid decision, else the requested amount. An Antrag in a denied state must count with 0 €. An
Antrag in a state with neither flag counts as requested. These places must use this rule:

- the budget overview (committed amount of a cost centre),
- the total `Bewilligt` (`Approved`) of an Event (000479),
- a transition into an approved state, which allows a decision with deviations (000132).

The lists `acceptedStateKeys` and `deniedStateKeys` of a top cost centre must go. A migration
must set the matching flag on every state whose key one of these lists holds. A key that one
list marks as accepted and another as denied must get neither flag, and the migration must go
on with the next state.

Reason: One rule gives the same approved amount in the budget and at the Event. Today the Event
counts only an Antrag with a stored decision, so it shows 0 € for a normal approval.

Test: A backend unit test approves an Antrag without a decision and checks the committed amount
of its cost centre and the total of its Event.
