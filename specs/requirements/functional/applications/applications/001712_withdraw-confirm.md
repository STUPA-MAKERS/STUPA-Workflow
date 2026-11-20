---
id: "001712"
title: A withdrawal asks first and does not show in a draft
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
implementation:
  - frontend/src/app/features/apply/status-timeline.component.ts
  - frontend/src/app/pages/admin/flow-graph.util.ts
scope:
  - backend/app/modules/applications
  - frontend/src/app/pages/applications
---

# A withdrawal asks first and does not show in a draft

A manual transition of the applicant into a terminal state must ask for a confirmation before
it fires. The detail of a draft must not offer such a transition to the applicant. The flow
editor must show a warning on such a transition out of the initial state.

Reason: Prod data holds one Antrag that was withdrawn by mistake. A draft that the applicant does not want can be left alone.

Test: A frontend unit test fires a transition into a terminal state and checks the confirmation.
