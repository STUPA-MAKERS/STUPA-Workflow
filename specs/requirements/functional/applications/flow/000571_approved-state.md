---
id: "000571"
title: A flow state can mark an Antrag as approved or denied
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-09
implementation:
  - backend/app/modules/flow/models.py
  - backend/app/shared/config_schemas.py
  - backend/app/modules/admin/service/flow.py
  - backend/migrations/versions/e4a91c27b6d3_state_outcome_flags.py
  - frontend/src/app/pages/admin/flow/state-inspector.component.html
  - frontend/src/app/pages/admin/flow/flow-graph-ops.util.ts
scope:
  - backend/app/modules/flow
  - frontend/src/app/pages/admin/flow
---

# A flow state can mark an Antrag as approved or denied

A state of a flow must have the flags `Bewilligt` (`approved`) and `Abgelehnt` (`denied`). The
flow editor must show each flag as a switch on the state. An Antrag in a state with a flag
counts as approved or denied. A state must not have both flags. A vote state must have neither,
because a vote state leads to its result through its pass and fail exits.

Reason: Whether an Antrag is approved or denied depends on its state in the flow. A list of
state keys at the cost centre breaks without a warning when a state gets a new key or a new
flow version.

Test: A backend unit test saves a flow with an approved and a denied state, and rejects both
flags on one state and a flag on a vote state.
