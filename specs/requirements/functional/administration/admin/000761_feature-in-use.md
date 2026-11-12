---
id: "000761"
title: A feature in use by the Antrag flow cannot go off
kind: functional
status: draft
owner: frederikbeimgraben
updated: 2026-11-12
implementation: null
scope:
  - backend/app/modules/admin
  - backend/app/modules/flow
  - frontend/src/app/pages/admin
---

# A feature in use by the Antrag flow cannot go off

The save must refuse to switch a feature off while the active flow or an Antragsart uses it, with
409 and the problem code `feature_in_use`. `Abstimmungen` is in use while a state of the flow
starts a vote. `Sitzungen` is in use while a transition puts the Antrag on the agenda of a
meeting. `Budget` is in use while a transition assigns a Kostenstelle or an Antragsart has a
budget. The page must name each use, so that the admin can remove it first.

The flow editor and the Antragsart editor must not offer a step that needs a feature that is off.

Reason: An Antrag must not stop in a state that waits for a vote or a meeting that nobody can
open.

Test: A backend unit test builds a flow with a vote state and gets 409 `feature_in_use` when it
switches `Abstimmungen` off. A second test saves a flow with a vote state while `Abstimmungen` is
off and gets 422.
