---
id: "000761"
title: A feature in use by the Antrag flow cannot go off
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-12
tests:
  - "backend/tests/integration/modules/features/test_features_api.py:test_a_feature_in_use_by_the_flow_cannot_go_off"
  - "backend/tests/integration/modules/features/test_features_api.py:test_a_flow_cannot_start_to_use_a_feature_that_is_off"
  - "backend/tests/integration/modules/features/test_features_api.py:test_budget_is_in_use_while_an_antragsart_has_a_budget"
  - "backend/tests/unit/modules/site_config/test_features.py:test_the_flow_uses_name_states_and_transitions"
implementation:
  - backend/app/modules/site_config/feature_uses.py
  - backend/app/modules/admin/site_config_service.py
  - backend/app/modules/admin/service/flow.py
  - backend/app/modules/admin/service/application_types.py
  - frontend/src/app/pages/admin/flow/transition-detail.component.ts
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

Test: `backend/tests/integration/modules/features/test_features_api.py` builds a flow with a vote
state and gets 409 `feature_in_use` when it switches `Abstimmungen` off. A second test saves a flow
with a vote state while `Abstimmungen` is off and gets 422.
