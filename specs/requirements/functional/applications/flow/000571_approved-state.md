---
id: "000571"
title: A flow state can mark an Antrag as approved
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-09
implementation: null
scope:
  - backend/app/modules/flow
  - frontend/src/app/pages/admin/flow-editor
---

# A flow state can mark an Antrag as approved

A state of a flow must have the flag `Bewilligt` (`approved`). The flow editor must show the flag
as a switch on the state. An Antrag in a state with the flag counts as approved. A vote state
must not have the flag, because a vote state leads to its result through its pass and fail
exits.

Reason: Whether an Antrag is approved depends on its state in the flow, not on its cost centre.

Test: A backend unit test saves a flow with an approved state and rejects the flag on a vote
state.
