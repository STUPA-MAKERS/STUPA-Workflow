---
id: "001603"
title: Recording a decision made outside the platform needs its own permission
kind: functional
status: approved
owner: frederikbeimgraben
updated: 2026-11-19
implementation: null
scope:
  - backend/app/modules/flow
  - backend/app/modules/admin
  - frontend/src/app/pages/admin
---

# Recording a decision made outside the platform needs its own permission

The permission `application.record_decision` must exist in the permission catalogue. A
migration must give it to the roles `finanzreferent` and `haushaltsbeauftragte` when these
roles exist. The button `Beschluss erfassen` (`Record decision`) must show only on an Antrag in
a vote state and only to a person with this permission.

Reason: The Finanzreferat and the Haushaltsbeauftragte record the decisions of the Gremien. `application.force_status` is too wide for this job, because it skips the flow.

Test: A backend unit test checks that a person without the permission gets 403.
